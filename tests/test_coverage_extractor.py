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


class _SampleTargets(unittest.TestCase):
    def setUp(self):
        targets = extract_targets(SAMPLE / "coverage.json", SAMPLE)
        self.targets = _by_name(t for t in targets if t.file == "app/service.py")
        self.ai = _by_name(t for t in targets if t.file == "app/ai_service.py")


class ExtractTargetsTest(_SampleTargets):

    def test_groups_gaps_by_function(self):
        self.assertEqual(set(self.targets), {"Grader.grade", "Grader.unused", None})
        self.assertEqual(set(self.ai), {"generate_with_retry", "summarize"})

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


class NeverCalledFunctionTest(_SampleTargets):
    """실제 프로젝트(ai_service.analyze_work_hours) 사례 재현: import만 되고 호출되지 않은 함수."""

    def test_fragments_merged_into_one_gap(self):
        # coverage.py는 빈 줄·여러 줄 문장의 이어지는 줄을 missing_lines에 넣지 않아 구간이 5개로 쪼개졌었다
        target = self.ai["summarize"]
        self.assertTrue(target.never_called)
        self.assertEqual([(g.kind, g.start_line, g.end_line) for g in target.gaps], [("line", 15, 34)])

    def test_continuation_lines_marked(self):
        lines = {int(l[3:7]): l[:2] for l in self.ai["summarize"].source.splitlines()}
        self.assertEqual(lines[22], ">>")  # 여러 줄 딕셔너리의 둘째 줄
        self.assertEqual(lines[28], ">>")  # 여러 줄 f-string 안
        self.assertEqual(lines[16], "  ")  # 빈 줄은 표시하지 않음

    def test_dependencies_listed_with_origin(self):
        deps = self.ai["summarize"].dependencies
        self.assertEqual(
            [d.split(":")[0] for d in deps], ["get_today_metrics", "generate_with_retry", "datetime"]
        )
        self.assertIn("from app.clients import get_today_metrics", deps[0])
        self.assertIn("같은 파일 함수", deps[1])

    def test_called_function_not_flagged(self):
        self.assertFalse(self.targets["Grader.grade"].never_called)

    def test_prompt_mentions_never_called_and_dependencies(self):
        prompt = build_prompt(self.ai["summarize"])
        self.assertIn("한 번도 호출되지 않았습니다", prompt)
        self.assertIn("from app.clients import get_today_metrics", prompt)
        self.assertIn("mock/patch", prompt)


class ModuleNameGuessTest(unittest.TestCase):
    def _extract(self, files: dict[str, str], target_file: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, text in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text, encoding="utf-8")
            coverage = {"files": {target_file: {"missing_lines": [5], "executed_lines": [1, 4]}}}
            (root / "coverage.json").write_text(json.dumps(coverage), encoding="utf-8")
            (target,) = extract_targets(root / "coverage.json", root)
        return target

    def test_flat_imports_under_app(self):
        # 실제 대상 프로젝트 방식: app/이 sys.path에 들어가 `from utils.kst import ...`로 import
        target = self._extract(
            {
                "app/utils/kst.py": "def now(): pass\n",
                "app/services/ai.py": "from utils.kst import now\nimport os\n\ndef f():\n    return now()\n",
            },
            "app/services/ai.py",
        )
        self.assertEqual(target.module_name, "services.ai")
        self.assertIn('patch("services.ai.now")', build_prompt(target))

    def test_package_imports_from_root(self):
        target = self._extract(
            {
                "app/utils/kst.py": "def now(): pass\n",
                "app/services/ai.py": "from app.utils.kst import now\nimport os\n\ndef f():\n    return now()\n",
            },
            "app/services/ai.py",
        )
        self.assertEqual(target.module_name, "app.services.ai")

    def test_sample_fixture(self):
        targets = extract_targets(SAMPLE / "coverage.json", SAMPLE)
        self.assertEqual({t.module_name for t in targets if t.file == "app/ai_service.py"}, {"app.ai_service"})


class DecisionPointsTest(unittest.TestCase):
    """첫 실호출에서 소형 모델이 hours <= 5 참 경로, except 경로, `or` 기본값 경로를 빠뜨린 사례에 대한 대응."""

    def _real_function(self):
        import ast

        from testgen.coverage_extractor import _decision_points, _dependencies, _module_symbols

        path = Path(__file__).parent / "fixtures" / "real_excerpts" / "analyze_work_hours.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        node = next(n for n in tree.body if getattr(n, "name", "") == "analyze_work_hours")
        return _decision_points(node), _dependencies(node, _module_symbols(tree, source.splitlines()))

    def test_real_analyze_work_hours_checklist(self):
        points, _ = self._real_function()
        text = "\n".join(points)
        self.assertIn("if `len(past_records) < 3`", text)
        self.assertIn("경계 3", text)
        self.assertIn("`record.work_seconds or 0`", text)
        self.assertIn("get_today_deep_work_metrics() or", text)
        self.assertIn("조건식(삼항) `slack_metrics.get('dnd_active')`", text)
        self.assertIn("if `hours <= 5`", text)
        self.assertIn("경계 5", text)
        self.assertIn("try → 정상 완료 / 예외 발생(Exception)", text)

    def test_annotation_only_dependency_marked(self):
        _, deps = self._real_function()
        session = next(d for d in deps if d.startswith("Session:"))
        attendance = next(d for d in deps if d.startswith("Attendance:"))
        self.assertIn("mock 불필요", session)
        self.assertNotIn("mock 불필요", attendance)

    def test_sample_targets_and_prompt(self):
        targets = {t.qualname: t for t in extract_targets(SAMPLE / "coverage.json", SAMPLE)}
        grade = targets["Grader.grade"]
        self.assertTrue(any("경계 0" in p and "경계 100" in p for p in grade.decision_points))
        self.assertTrue(any("반복 `range(score)` → 0회 / 1회 이상" in p for p in grade.decision_points))
        prompt = build_prompt(grade)
        self.assertIn("분기·조건 체크리스트 (4개", prompt)
        self.assertIn("side_effect", prompt)

    def test_signature_excludes_inner_decorator(self):
        targets = {t.qualname: t for t in extract_targets(SAMPLE / "coverage.json", SAMPLE)}
        deps = targets["Grader.grade"].dependencies
        self.assertEqual(deps, ["logged: 같은 파일 함수 (라인 4): def logged(fn):"])


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
