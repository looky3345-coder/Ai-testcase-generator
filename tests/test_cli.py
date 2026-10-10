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
