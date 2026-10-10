import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from testgen.cli import main

SAMPLE = Path(__file__).parent / "fixtures" / "sample_project"


def _run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CoverageJsonPathTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.output_dir = Path(tmp.name) / "out"

    def test_folder_resolves_to_coverage_json_inside(self):
        # 사용자 실수 사례: 파일 대신 backend 폴더를 넘김
        code, out, _ = _run(
            "--coverage-json", str(SAMPLE), "--source-root", str(SAMPLE),
            "--output-dir", str(self.output_dir), "--dry-run",
        )
        self.assertEqual(code, 0)
        self.assertIn("폴더라서", out)
        self.assertTrue((self.output_dir / "targets.json").is_file())

    def test_folder_without_coverage_json(self):
        empty = self.output_dir.parent / "empty"
        empty.mkdir()
        code, _, err = _run("--coverage-json", str(empty), "--source-root", str(SAMPLE), "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("폴더 안에 coverage.json이 없습니다", err)

    def test_wrong_source_root_warns(self):
        code, _, err = _run(
            "--coverage-json", str(SAMPLE / "coverage.json"), "--source-root", str(self.output_dir.parent),
            "--output-dir", str(self.output_dir), "--dry-run",
        )
        self.assertEqual(code, 0)
        self.assertIn("--source-root가 맞는지", err)



class CasesCsvTest(unittest.TestCase):
    def test_llm_run_writes_cases_csv(self):
        import csv
        import json as _json

        from tests.test_llm_runner import _FakeOpenAIServer

        case = {
            "id": "TC-1", "technique": "boundary_value_analysis", "description": "경계 확인",
            "target_lines": "14->15", "preconditions": "", "input": "score=101",
            "expected": "ValueError", "priority": "high",
        }
        duplicate = dict(case, id="TC-2", description="같은 입력")
        fake = _FakeOpenAIServer(content=_json.dumps({"test_cases": [case, duplicate]}))
        self.addCleanup(fake.close)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            code, stdout, _ = _run(
                "--coverage-json", str(SAMPLE), "--source-root", str(SAMPLE), "--output-dir", str(out),
                "--models", "local:m", "--local-base-url", fake.base_url, "--qualname", "grade", "--workers", "1",
            )
            self.assertEqual(code, 0)
            self.assertIn("test_cases.csv", stdout)
            raw = (out / "test_cases.csv").read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))  # 엑셀 한글 표시용 BOM
            with (out / "test_cases.csv").open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        self.assertIn("OK, 케이스 2개 (중복 의심 1건)", stdout)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["function"], "Grader.grade")
        self.assertEqual(rows[0]["model"], "local-m")
        self.assertEqual(rows[0]["description"], "경계 확인")
        self.assertEqual(rows[0]["review_note"], "")
        self.assertIn("중복 의심", rows[1]["review_note"])


class SwallowedQuoteTest(unittest.TestCase):
    def test_trailing_backslash_hint(self):
        # PowerShell에서 --coverage-json "C:\\x\\backend\\" --source-root "..." 를 입력했을 때 Python이 받는 값
        broken = ["--coverage-json", 'C:\\x\\backend" --source-root C:\\x\\backend"', "--dry-run"]
        code = None
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            try:
                main(broken)
            except SystemExit as exc:  # argparse가 --source-root 누락으로 종료
                code = exc.code
        self.assertEqual(code, 2)
        self.assertIn("경로 끝의", err.getvalue())

    def test_no_hint_for_normal_args(self):
        from testgen.cli import warn_swallowed_quote

        with redirect_stderr(io.StringIO()):
            self.assertFalse(warn_swallowed_quote(["--coverage-json", "C:\\x\\backend", "--dry-run"]))


class ModelPreflightTest(unittest.TestCase):
    def test_wrong_model_stops_before_any_call(self):
        from tests.test_llm_runner import _FakeOpenAIServer

        fake = _FakeOpenAIServer(models=["hf.co/x/y:Q4_K_M"])
        self.addCleanup(fake.close)
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = _run(
                "--coverage-json", str(SAMPLE), "--source-root", str(SAMPLE), "--output-dir", tmp,
                "--models", "local:ornith15-9b", "--local-base-url", fake.base_url,
            )
        self.assertEqual(code, 1)
        self.assertIn("hf.co/x/y:Q4_K_M", err)
        self.assertEqual(fake.requests, [])  # chat/completions 호출 0건


class EmptyContentTest(unittest.TestCase):
    def test_reasoning_only_response_explained(self):
        # 실제 사례 재현: Ornith-1.5-9B가 46초 생성 후 content는 비고 reasoning만 반환
        import json as _json

        from tests.test_llm_runner import _FakeOpenAIServer

        body = _json.dumps({"choices": [{"message": {"content": "", "reasoning": "생각" * 50}, "finish_reason": "stop"}]})
        fake = _FakeOpenAIServer(raw_body=body)
        self.addCleanup(fake.close)
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = _run(
                "--coverage-json", str(SAMPLE), "--source-root", str(SAMPLE), "--output-dir", tmp,
                "--models", "local:m", "--local-base-url", fake.base_url, "--qualname", "grade",
                "--local-thinking", "on",
            )
            saved = _json.loads(next((Path(tmp) / "responses").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertIn("사고 과정(reasoning, 100자)만 있음", out)
        self.assertIn("성공 0건 (케이스 0개) / 파싱 실패 1건", out)  # 성공·실패 이중 집계 회귀 방지
        self.assertEqual(saved["finish_reason"], "stop")
        self.assertIn("reasoning", saved["raw_response"])


class TruncatedResponseTest(unittest.TestCase):
    def test_length_finish_reason_flagged_once(self):
        import json as _json

        from tests.test_llm_runner import _FakeOpenAIServer

        body = _json.dumps({
            "choices": [{"message": {"content": '{"test_cases": ['}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 2600, "completion_tokens": 1496},
        })
        fake = _FakeOpenAIServer(raw_body=body)
        self.addCleanup(fake.close)
        with tempfile.TemporaryDirectory() as tmp:
            _, out, _ = _run(
                "--coverage-json", str(SAMPLE), "--source-root", str(SAMPLE), "--output-dir", tmp,
                "--models", "local:m", "--local-base-url", fake.base_url, "--qualname", "grade",
            )
        self.assertIn("PARSE FAIL", out)
        self.assertIn("finish_reason=length", out)
        self.assertIn("입력 2600 + 출력 1496 = 4096 토큰", out)
        self.assertIn("성공 0건 (케이스 0개) / 파싱 실패 1건", out)


class FilterTargetsTest(unittest.TestCase):
    def test_qualname_filter(self):
        from testgen.cli import filter_targets
        from testgen.coverage_extractor import extract_targets

        targets = extract_targets(SAMPLE / "coverage.json", SAMPLE)
        self.assertEqual([t.qualname for t in filter_targets(targets, "all", None, None, "grade")], ["Grader.grade"])
        self.assertEqual(
            [t.qualname for t in filter_targets(targets, "all", None, None, "Grader.unused")], ["Grader.unused"]
        )
        self.assertEqual(filter_targets(targets, "all", None, None, "nope"), [])

if __name__ == "__main__":
    unittest.main()
