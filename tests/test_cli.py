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
        fake = _FakeOpenAIServer(content=_json.dumps({"test_cases": [case]}))
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
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["function"], "Grader.grade")
        self.assertEqual(rows[0]["model"], "local-m")
        self.assertEqual(rows[0]["description"], "경계 확인")


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
