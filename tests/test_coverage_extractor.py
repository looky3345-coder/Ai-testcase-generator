import json
import tempfile
import unittest
from pathlib import Path

from testgen.coverage_extractor import extract_targets
from testgen.prompt_builder import build_prompt

# 실제 pytest-cov 7.x(--cov-branch)가 만든 coverage.json을 줄여 둔 픽스처
SAMPLE = Path(__file__).parent / "fixtures" / "sample_project"


def _by_name(targets):
    return {t.qualname: t for t in targets}


class ExtractTargetsTest(unittest.TestCase):
    def setUp(self):
        self.targets = _by_name(extract_targets(SAMPLE / "coverage.json", SAMPLE))

    def test_groups_gaps_by_function(self):
        self.assertEqual(set(self.targets), {"Grader.grade", "Grader.unused", None})

    def test_branch_direction_kept(self):
        arcs = {(g.start_line, g.branch_target) for g in self.targets["Grader.grade"].gaps if g.kind == "branch"}
        self.assertEqual(arcs, {(14, 15), (16, 17), (18, 21), (19, 18)})

    def test_branches_from_unexecuted_lines_dropped(self):
        # unused()는 통째로 미실행: 라인 25의 분기 [25,26],[25,27]은 라인 갭과 중복이라 버린다
        gaps = self.targets["Grader.unused"].gaps
        self.assertEqual([(g.kind, g.start_line, g.end_line) for g in gaps], [("line", 24, 27)])

    def test_whole_function_with_decorator_and_markers(self):
        target = self.targets["Grader.grade"]
        self.assertFalse(target.truncated)
        lines = target.source.splitlines()
        self.assertIn("@logged", lines[0])
        self.assertTrue(lines[-1].strip().endswith('return "B"'))
        self.assertTrue(any(l.startswith(">>") and "raise ValueError" in l for l in lines))
        self.assertTrue(any(l.startswith("B>") and "if score >= 90" in l for l in lines))

    def test_module_level_context_stops_at_function_boundary(self):
        source = self.targets[None].source
        self.assertIn("if TIMEOUT > 10", source)
        self.assertNotIn("return 3", source)  # 바로 위 unused() 본문이 섞이면 안 된다

    def test_prompt_lists_every_gap(self):
        target = self.targets["Grader.grade"]
        prompt = build_prompt(target)
        for gap in target.gaps:
            self.assertIn(gap.describe(), prompt)
        self.assertIn("라인 19의 분기: 라인 18(으)로 가는 경로", prompt)


class LongFunctionTest(unittest.TestCase):
    def test_long_function_truncated_around_gaps(self):
        body = "\n".join(f"    x{i} = {i}" for i in range(200))
        source = f"@decorator\ndef long_fn(a,\n            b):\n{body}\n    return a\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod.py").write_text(source, encoding="utf-8")
            coverage = {"files": {"mod.py": {"missing_lines": [150], "missing_branches": []}}}
            (root / "coverage.json").write_text(json.dumps(coverage), encoding="utf-8")
            (target,) = extract_targets(root / "coverage.json", root)

        self.assertTrue(target.truncated)
        self.assertIn("@decorator", target.source)
        self.assertIn("b):", target.source)  # 여러 줄 시그니처 헤더 유지
        self.assertIn(">>  150:", target.source)
        self.assertIn("...", target.source)
        self.assertNotIn("x100 =", target.source)


if __name__ == "__main__":
    unittest.main()
