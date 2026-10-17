import importlib.util
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from testgen.codegen import (
    ProjectTestContext,
    build_codegen_prompt,
    collect_project_context,
    extract_code,
    generate_and_run,
    prune_failing,
)
from testgen.coverage_extractor import extract_targets
from testgen.llm_runner import LLMBackend
from testgen.models import LLMResponse

SAMPLE = Path(__file__).parent / "fixtures" / "sample_project"


def _pytest_python() -> str | None:
    """생성 테스트를 실제로 돌릴 Python. 도구 자체는 표준 라이브러리만 쓰므로 pytest-cov가 없을 수 있다.
    TESTGEN_TEST_PYTHON 환경변수로 pytest + pytest-cov가 설치된 Python을 지정하면 실행 테스트도 돈다."""
    if os.environ.get("TESTGEN_TEST_PYTHON"):
        return os.environ["TESTGEN_TEST_PYTHON"]
    if importlib.util.find_spec("pytest_cov"):
        return sys.executable
    return None


class ExtractCodeTest(unittest.TestCase):
    def test_fenced_code_and_think(self):
        code, error = extract_code("<think>음 {x}</think>설명\n```python\ndef test_a():\n    assert 1\n```\n끝")
        self.assertIsNone(error)
        self.assertIn("def test_a", code)

    def test_syntax_error(self):
        code, error = extract_code("```python\ndef test_a(:\n```")
        self.assertIsNone(code)
        self.assertIn("문법 오류", error)

    def test_empty(self):
        self.assertEqual(extract_code("")[1], "모델 출력에 코드가 없습니다")


class PruneFailingTest(unittest.TestCase):
    CODE = textwrap.dedent(
        """
        import pytest

        def helper():
            return 1

        def test_ok():
            assert helper() == 1

        @pytest.mark.parametrize("x", [1, 2])
        def test_param(x):
            assert x == 1

        class TestGroup:
            def test_in_class(self):
                assert False

            def test_in_class_ok(self):
                assert True
        """
    )

    def test_removes_failed_functions_keeps_rest(self):
        pruned = prune_failing(self.CODE, ["test_param[2]", "test_in_class"])
        self.assertIn("def test_ok", pruned)
        self.assertIn("def helper", pruned)
        self.assertIn("def test_in_class_ok", pruned)
        self.assertNotIn("def test_param", pruned)  # 한 경우라도 실패하면 함수 전체 제거
        self.assertNotIn("def test_in_class(", pruned)

    def test_none_when_nothing_left(self):
        self.assertIsNone(prune_failing("def test_a():\n    assert False\n", ["test_a"]))


class ProjectContextTest(unittest.TestCase):
    def test_fixtures_and_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests = Path(tmp) / "tests"
            tests.mkdir()
            (tests / "conftest.py").write_text(
                textwrap.dedent(
                    '''
                    import pytest

                    @pytest.fixture(scope="session")
                    def setup_db():
                        """테스트 유저 생성."""

                    @pytest.fixture
                    def user_headers(user_token):
                        return {}

                    def not_a_fixture():
                        pass
                    '''
                ),
                encoding="utf-8",
            )
            (tests / "test_x.py").write_text("import datetime\nfrom services.leave_service import calc\n", encoding="utf-8")
            context = collect_project_context(Path(tmp))
        self.assertEqual(
            context.fixtures, ["setup_db (scope=session) — 테스트 유저 생성.", "user_headers [의존: user_token]"]
        )
        self.assertEqual(context.import_examples, ["import datetime", "from services.leave_service import calc"])


def _grade_target():
    return next(t for t in extract_targets(SAMPLE / "coverage.json", SAMPLE) if t.qualname == "Grader.grade")


def _cases_response():
    case = {
        "id": "TC-1", "technique": "boundary_value_analysis", "description": "범위 밖", "target_lines": "14->15",
        "preconditions": "", "input": "score=101", "expected": "ValueError", "priority": "high",
    }
    return LLMResponse(model="fake", target_id="t", ok=True, raw_output="", error=None, elapsed_sec=0.0,
                       test_cases=[case], common_preconditions="")


class PromptTest(unittest.TestCase):
    def test_codegen_prompt_has_import_path_cases_and_fixtures(self):
        target = _grade_target()
        prompt = build_codegen_prompt(
            target, _cases_response(), ProjectTestContext(fixtures=["client (scope=session)"]),
            "tests/_ai_generated/test_x.py", "FastAPI",
        )
        self.assertIn("`from app import service`로 import", prompt)
        self.assertIn('patch("app.service.<이름>")', prompt)
        self.assertIn('"score=101"', prompt)
        self.assertIn("- client (scope=session)", prompt)
        self.assertNotIn(">>", prompt.split("소스:")[1].split("```")[1])  # 미실행 표시는 코드 생성 프롬프트에서 제거


class _ScriptedBackend(LLMBackend):
    """미리 정한 출력을 차례로 돌려주는 가짜 LLM (코드 생성 라운드별)."""

    def __init__(self, outputs):
        self.name = "fake"
        self.outputs = list(outputs)
        self.prompts = []

    def run(self, target_id, prompt, structured=True):
        self.prompts.append((prompt, structured))
        return LLMResponse(model=self.name, target_id=target_id, ok=True, raw_output=self.outputs.pop(0),
                           error=None, elapsed_sec=0.0)


GOOD = '''```python
import pytest
from app.service import Grader

@pytest.mark.parametrize("score", [-1, 101])
def test_tc1_out_of_range(score):
    with pytest.raises(ValueError):
        Grader().grade(score)

def test_tc2_a():
    assert Grader().grade(90) == "A"

def test_tc3_b_loop_and_zero():
    assert Grader().grade(10) == "B"
    assert Grader().grade(0) == "B"
    assert Grader().grade(50) == "B"  # 반복 중 break
```'''

ONE_FAILING = GOOD.replace("```python\n", "```python\ndef test_tc9_wrong():\n    assert Grader().grade(95) == 'B'\n\n")


@unittest.skipUnless(_pytest_python(), "pytest + pytest-cov가 있는 Python이 필요 (TESTGEN_TEST_PYTHON)")
class GenerateAndRunTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "project"
        shutil.copytree(SAMPLE, self.root)
        self.out = Path(tmp.name) / "out"
        self.target = next(t for t in extract_targets(self.root / "coverage.json", self.root) if t.qualname == "Grader.grade")

    def _run(self, backend, rounds=2):
        return generate_and_run(
            self.target, _cases_response(), backend, self.root, self.out, _pytest_python(),
            ProjectTestContext(), fix_rounds=rounds, timeout=120, log=lambda m: None,
        )

    def test_feedback_round_fixes_failure_and_accepts(self):
        backend = _ScriptedBackend([ONE_FAILING, GOOD])
        report = self._run(backend)
        self.assertEqual(report.status, "accepted", report)
        self.assertEqual(len(report.rounds), 2)
        self.assertEqual(report.rounds[0]["failed"], ["test_tc9_wrong"])
        self.assertIn("test_tc9_wrong", backend.prompts[1][0])  # 실패 메시지가 수정 프롬프트에 전달됨
        self.assertFalse(backend.prompts[0][1])  # 코드 생성은 JSON 스키마 강제 없이 호출
        self.assertTrue((self.root / report.test_file).is_file())
        self.assertEqual(report.uncovered_lines, [])

    def test_persistent_failure_is_pruned(self):
        report = self._run(_ScriptedBackend([ONE_FAILING, ONE_FAILING]), rounds=1)
        self.assertEqual(report.status, "partial")
        self.assertEqual(report.removed_tests, ["test_tc9_wrong"])
        kept = (self.root / report.test_file).read_text(encoding="utf-8")
        self.assertNotIn("test_tc9_wrong", kept)
        self.assertIn("test_tc2_a", kept)

    def test_import_error_rejected_and_file_removed(self):
        broken = "```python\nfrom app.nope import X\n\ndef test_a():\n    assert X\n```"
        report = self._run(_ScriptedBackend([broken, broken]), rounds=1)
        self.assertEqual(report.status, "rejected")
        self.assertIsNone(report.test_file)
        self.assertEqual(list((self.root / "tests" / "_ai_generated").glob("test_*.py")), [])

    def test_syntax_error_retried(self):
        report = self._run(_ScriptedBackend(["```python\ndef test(:\n```", GOOD]))
        self.assertEqual(report.status, "accepted")
        self.assertIn("문법 오류", report.rounds[0]["error"])


if __name__ == "__main__":
    unittest.main()
