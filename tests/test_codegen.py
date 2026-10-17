import dataclasses
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
    RunResult,
    TestOutcome,
    build_codegen_prompt,
    build_fix_prompt,
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


# 2026-10-17 사용자 PC 실행(analyze_work_hours, Ornith-1.5-9B)에서 실제로 나온 실패 메시지 형태
_FALLBACK_SOURCE = (
    "    146:     try:\n"
    "    147:         return generate_with_retry(prompt, max_tokens=80)\n"
    "    148:     except Exception as e:\n"
    "    149:         print(f\"GEMINI ERROR: {str(e)}\")\n"
    "    150:         return \"AI 매니저가 잠시 디버깅 중이에요! 🛠️ 곧 위트 있는 분석을 가져올게요.\"\n"
)
_FALLBACK_MESSAGE = (
    "AssertionError: assert 'AI 매니저가 잠시 디...있는 분석을 가져올게요.' == '완벽한 하루였어! 🌙'\n"
    "  - 완벽한 하루였어! 🌙\n  + AI 매니저가 잠시 디버깅 중이에요! 🛠️ 곧 위트 있는 분석을 가져올게요."
)


def _fallback_target():
    source = "    106: def analyze_work_hours(db, user_id, current_work_seconds):\n" + _FALLBACK_SOURCE
    return dataclasses.replace(_grade_target(), qualname="analyze_work_hours", source=source)


def _failed(message):
    return RunResult(returncode=1, tests=[TestOutcome(name="test_tc1", outcome="failed", message=message)])


class FixPromptHintTest(unittest.TestCase):
    def test_rule8_in_both_prompts(self):
        target = _grade_target()
        codegen = build_codegen_prompt(target, _cases_response(), ProjectTestContext(), "tests/x.py", None)
        fix = build_fix_prompt(target, "def test_a(): pass\n", _failed("AssertionError"))
        for prompt in (codegen, fix):
            self.assertIn("8. patch는 반드시 적용된 상태에서", prompt)

    def test_patch_object_not_started_hint(self):
        prompt = build_fix_prompt(
            _grade_target(), "x = 1\n", _failed("AttributeError: '_patch' object has no attribute 'call_args'")
        )
        self.assertIn("원인 힌트:", prompt)
        self.assertIn("적용(with/start())하지 않았습니다", prompt)

    def test_except_path_result_hint(self):
        prompt = build_fix_prompt(_fallback_target(), "x = 1\n", _failed(_FALLBACK_MESSAGE))
        self.assertIn("except 경로 반환값", prompt)
        self.assertIn("'AI 매니저가 잠시...'", prompt)  # 리터럴 앞 10자 + ...

    def test_no_hint_for_ordinary_failure(self):
        prompt = build_fix_prompt(_fallback_target(), "x = 1\n", _failed("AssertionError: assert 3 == 4"))
        self.assertNotIn("원인 힌트:", prompt)

    def test_unparsable_source_has_no_literals_and_no_crash(self):
        target = dataclasses.replace(_grade_target(), source="    1: def broken(:\n")
        prompt = build_fix_prompt(target, "x = 1\n", _failed(_FALLBACK_MESSAGE))
        self.assertNotIn("except 경로 반환값", prompt)


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
