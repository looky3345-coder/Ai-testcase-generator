"""1단계: pytest-cov가 생성한 coverage.json에서 미커버 코드 경로를 추출한다.

분석 대상 프로젝트에서 먼저 coverage.json을 만들어야 한다. 예:
    python -m pytest tests/ --cov=app --cov-branch --cov-report=json:coverage.json
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from testgen.config import SNIPPET_CONTEXT_LINES
from testgen.models import CoverageGap

# 소스 자체가 아닌 것들(테스트 코드, 마이그레이션)은 갭 추출 대상에서 제외
_EXCLUDED_PARTS = {"tests", "test", "migrations"}


def _to_posix(path_str: str) -> str:
    return path_str.replace("\\", "/")


def _group_consecutive(lines: list[int]) -> list[tuple[int, int]]:
    """정렬된 라인 번호 리스트를 연속 구간 [(start, end), ...] 로 묶는다."""
    if not lines:
        return []
    ordered = sorted(set(lines))
    ranges: list[tuple[int, int]] = []
    start = prev = ordered[0]
    for n in ordered[1:]:
        if n == prev + 1:
            prev = n
            continue
        ranges.append((start, prev))
        start = prev = n
    ranges.append((start, prev))
    return ranges


def _iter_functions(tree: ast.AST):
    """(qualname, node) 를 클래스 중첩까지 고려해서 전부 순회한다."""

    def walk(node: ast.AST, prefix: str):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}.{child.name}" if prefix else child.name
                yield qualname, child
                yield from walk(child, qualname)
            elif isinstance(child, ast.ClassDef):
                new_prefix = f"{prefix}.{child.name}" if prefix else child.name
                yield from walk(child, new_prefix)
            else:
                yield from walk(child, prefix)

    yield from walk(tree, "")


def _enclosing_function(functions: list[tuple[str, ast.AST]], line: int):
    """주어진 라인을 감싸는 함수 중 범위가 가장 좁은(가장 안쪽) 것을 고른다."""
    candidates = [
        (qualname, node)
        for qualname, node in functions
        if node.lineno <= line <= (node.end_lineno or node.lineno)
    ]
    if not candidates:
        return None, None
    qualname, node = min(candidates, key=lambda item: item[1].end_lineno - item[1].lineno)
    return qualname, node


def _build_signature(source_lines: list[str], node: ast.AST) -> str:
    body_start = node.body[0].lineno if node.body else node.lineno + 1
    header = source_lines[node.lineno - 1 : body_start - 1]
    text = " ".join(line.strip() for line in header if line.strip())
    return text or source_lines[node.lineno - 1].strip()


def _build_snippet(
    source_lines: list[str],
    gap_start: int,
    gap_end: int,
    bound_start: int,
    bound_end: int,
) -> tuple[str, int]:
    lo = max(bound_start, gap_start - SNIPPET_CONTEXT_LINES, 1)
    hi = min(bound_end, gap_end + SNIPPET_CONTEXT_LINES, len(source_lines))
    rows = []
    for lineno in range(lo, hi + 1):
        marker = ">>" if gap_start <= lineno <= gap_end else "  "
        text = source_lines[lineno - 1].rstrip("\n")
        rows.append(f"{marker} {lineno:>4}: {text}")
    return "\n".join(rows), lo


def _make_gap(
    rel_path: str,
    kind: str,
    start_line: int,
    end_line: int,
    source_lines: list[str],
    functions: list[tuple[str, ast.AST]],
) -> CoverageGap:
    qualname, node = _enclosing_function(functions, start_line)
    if node is not None:
        signature = _build_signature(source_lines, node)
        bound_start, bound_end = node.lineno, node.end_lineno
    else:
        signature = None
        bound_start, bound_end = 1, len(source_lines)

    snippet, snippet_start = _build_snippet(
        source_lines, start_line, end_line, bound_start, bound_end
    )

    return CoverageGap(
        file=rel_path,
        kind=kind,
        start_line=start_line,
        end_line=end_line,
        qualname=qualname,
        signature=signature,
        snippet=snippet,
        snippet_start_line=snippet_start,
    )


def _gaps_for_file(rel_path: str, abs_path: Path, file_report: dict) -> list[CoverageGap]:
    if any(part in _EXCLUDED_PARTS for part in Path(rel_path).parts):
        return []
    if not abs_path.is_file():
        return []

    source = abs_path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=str(abs_path))
    except SyntaxError:
        return []
    functions = list(_iter_functions(tree))

    gaps: list[CoverageGap] = []

    for start, end in _group_consecutive(file_report.get("missing_lines", [])):
        gaps.append(_make_gap(rel_path, "line", start, end, source_lines, functions))

    branch_lines = sorted({pair[0] for pair in file_report.get("missing_branches", [])})
    for line in branch_lines:
        gaps.append(_make_gap(rel_path, "branch", line, line, source_lines, functions))

    return gaps


def extract_gaps(coverage_json_path: Path, source_root: Path) -> list[CoverageGap]:
    """coverage.json을 읽어 파일 전체의 CoverageGap 목록을 만든다.

    coverage.json 안의 파일 경로는 source_root 기준 상대경로라고 가정한다
    (예: source_root=<target>/backend, "app/routers/attendance.py").
    """
    data = json.loads(Path(coverage_json_path).read_text(encoding="utf-8"))
    all_gaps: list[CoverageGap] = []

    for raw_path, file_report in data.get("files", {}).items():
        rel_path = _to_posix(raw_path)
        abs_path = (source_root / raw_path).resolve()
        all_gaps.extend(_gaps_for_file(rel_path, abs_path, file_report))

    return all_gaps
