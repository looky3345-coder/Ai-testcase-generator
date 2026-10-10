"""1단계: pytest-cov가 생성한 coverage.json에서 미커버 코드 경로를 추출해 함수 단위로 묶는다.

분석 대상 프로젝트에서 먼저 coverage.json을 만들어야 한다. 예:
    python -m pytest tests/ --cov=app --cov-branch --cov-report=json:coverage.json

LLM 호출 단위는 갭이 아니라 함수(TestTarget)다. 한 함수 안의 갭을 모아 한 번에 보내면
호출 수가 줄고, 모델이 함수 전체 흐름(갭에 도달하는 조건식 = 경계값의 근거)을 볼 수 있다.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from testgen.config import LONG_FUNCTION_CONTEXT_LINES, MAX_FUNCTION_LINES, MODULE_CONTEXT_LINES
from testgen.models import CoverageGap, TestTarget

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
        if _def_start(node) <= line <= (node.end_lineno or node.lineno)
    ]
    if not candidates:
        return None, None
    return min(candidates, key=lambda item: item[1].end_lineno - _def_start(item[1]))


def _def_start(node: ast.AST) -> int:
    """데코레이터까지 포함한 함수 시작 라인. FastAPI 라우트 등은 데코레이터가 핵심 정보다."""
    return min([node.lineno, *(d.lineno for d in node.decorator_list)])


def _build_signature(source_lines: list[str], node: ast.AST) -> str:
    body_start = node.body[0].lineno if node.body else node.lineno + 1
    header = source_lines[node.lineno - 1 : body_start - 1]
    text = " ".join(line.strip() for line in header if line.strip())
    return text or source_lines[node.lineno - 1].strip()


def _missing_statement_lines(tree: ast.AST, missing: set[int]) -> set[int]:
    """미실행 문장이 차지하는 모든 라인. coverage.py는 여러 줄 문장의 첫 줄만 보고하므로
    (예: 여러 줄 f-string, 딕셔너리) 이어지는 줄도 미실행으로 표시하기 위해 문장 범위로 넓힌다.
    if/for/try 같은 복합문은 머리가 미실행이면 본문 전체도 미실행이므로 그대로 넓혀도 맞다."""
    lines = set(missing)
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and node.lineno in missing:
            lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


def _merge_line_ranges(
    ranges: list[tuple[int, int]], executed: set[int] | None, functions: list[tuple[str, ast.AST]]
) -> list[tuple[int, int]]:
    """사이에 실행된 라인이 하나도 없는 미실행 구간끼리 합친다 (빈 줄·이어지는 줄 때문에 쪼개진 것).
    다른 함수의 구간끼리는 합치지 않는다. executed 정보가 없으면 그대로 둔다."""
    if executed is None:
        return ranges
    merged: list[tuple[int, int]] = []
    for lo, hi in ranges:
        if merged:
            prev_lo, prev_hi = merged[-1]
            same_function = _enclosing_function(functions, prev_lo)[1] is _enclosing_function(functions, lo)[1]
            if same_function and not any(prev_hi < line < lo for line in executed):
                merged[-1] = (prev_lo, hi)
                continue
        merged.append((lo, hi))
    return merged


def _module_symbols(tree: ast.Module, source_lines: list[str]) -> dict[str, str]:
    """모듈 최상위에서 정의/임포트된 이름 → 한 줄 설명. 함수가 참조하는 의존성을 알려주는 데 쓴다."""
    symbols: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for alias in node.names:
                suffix = f" as {alias.asname}" if alias.asname else ""
                symbols[alias.asname or alias.name] = f"from {module} import {alias.name}{suffix}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                suffix = f" as {alias.asname}" if alias.asname else ""
                symbols[alias.asname or alias.name.split(".")[0]] = f"import {alias.name}{suffix}"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols[node.name] = f"같은 파일 함수 (라인 {node.lineno}): {_build_signature(source_lines, node)}"
        elif isinstance(node, ast.ClassDef):
            symbols[node.name] = f"같은 파일 클래스 (라인 {node.lineno})"
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            text = source_lines[node.lineno - 1].strip()
            text = text if len(text) <= 100 else text[:97] + "..."
            for target in targets:
                if isinstance(target, ast.Name):
                    symbols[target.id] = f"모듈 변수 (라인 {node.lineno}): {text}"
    return symbols


def _dependencies(node: ast.AST, symbols: dict[str, str]) -> list[str]:
    """함수 안에서 읽는 이름 중 모듈 수준 임포트/정의에 해당하는 것 (등장 순서)."""
    own_name = getattr(node, "name", None)
    names = sorted(
        (n for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)),
        key=lambda n: (n.lineno, n.col_offset),
    )
    seen: list[str] = []
    for n in names:
        if n.id in symbols and n.id != own_name and n.id not in seen:
            seen.append(n.id)
    return [f"{name}: {symbols[name]}" for name in seen]


def _guess_module_name(rel_path: str, tree: ast.Module, source_root: Path) -> str:
    """테스트 실행 시 이 파일이 어떤 모듈 이름으로 import되는지 추정한다 (mock.patch 경로용).

    대상 프로젝트가 `from services.x import y`처럼 sys.path에 하위 폴더(예: app/)를 넣고 쓰면
    모듈 이름은 `app.services.ai_service`가 아니라 `services.ai_service`가 된다.
    같은 파일의 절대 import가 가리키는 최상위 이름이 어느 폴더 아래에 실제로 있는지로 기준 폴더를 고른다.
    """
    parts = Path(rel_path).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    top_names = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            top_names.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            top_names.update(alias.name.split(".")[0] for alias in node.names)

    best_depth, best_hits = 0, 0
    for depth in range(len(parts)):  # 기준 폴더 후보: source_root, source_root/parts[0], ...
        root = source_root.joinpath(*parts[:depth])
        hits = sum(1 for name in top_names if (root / name).is_dir() or (root / f"{name}.py").is_file())
        if hits > best_hits:
            best_depth, best_hits = depth, hits
    return ".".join(parts[best_depth:])


def _merge_windows(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for lo, hi in sorted(windows):
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def _render_source(
    source_lines: list[str],
    windows: list[tuple[int, int]],
    missing: set[int],
    partial: set[int],
) -> str:
    """구간들을 라인 번호 + 마커와 함께 렌더링한다. 구간 사이는 '...'로 표시."""
    blocks = []
    for lo, hi in _merge_windows(windows):
        rows = []
        for lineno in range(lo, hi + 1):
            marker = ">>" if lineno in missing else "B>" if lineno in partial else "  "
            rows.append(f"{marker} {lineno:>4}: {source_lines[lineno - 1].rstrip()}")
        blocks.append("\n".join(rows))
    return "\n   ...\n".join(blocks)


def _gap_windows(gaps: list[CoverageGap], context: int, lo_bound: int, hi_bound: int) -> list[tuple[int, int]]:
    return [
        (max(lo_bound, g.start_line - context), min(hi_bound, g.end_line + context))
        for g in gaps
    ]


def _module_windows(gaps: list[CoverageGap], function_spans: list[tuple[int, int]], n_lines: int) -> list[tuple[int, int]]:
    """모듈 레벨 갭 주변 구간. 앞뒤 문맥이 다른 함수 본문으로 넘어가지 않도록 함수 경계에서 자른다."""
    windows = []
    for gap, (lo, hi) in zip(gaps, _gap_windows(gaps, MODULE_CONTEXT_LINES, 1, n_lines)):
        for f_start, f_end in function_spans:
            if f_end < gap.start_line and f_end >= lo:
                lo = f_end + 1
            if f_start > gap.end_line and f_start <= hi:
                hi = f_start - 1
        windows.append((lo, hi))
    return windows


def _build_target(
    rel_path: str,
    qualname: str | None,
    node: ast.AST | None,
    gaps: list[CoverageGap],
    source_lines: list[str],
    missing: set[int],
    partial: set[int],
    function_spans: list[tuple[int, int]],
    executed: set[int] | None,
    symbols: dict[str, str],
    module_name: str,
) -> TestTarget:
    if node is None:
        # 모듈 레벨 코드: 파일 전체는 너무 크므로 갭 주변만
        windows = _module_windows(gaps, function_spans, len(source_lines))
        return TestTarget(
            file=rel_path,
            qualname=None,
            start_line=gaps[0].start_line,
            signature=None,
            source=_render_source(source_lines, windows, missing, partial),
            truncated=True,
            gaps=gaps,
            module_name=module_name,
        )

    start, end = _def_start(node), node.end_lineno
    truncated = end - start + 1 > MAX_FUNCTION_LINES
    if truncated:
        # 긴 함수: 데코레이터+시그니처 헤더는 항상 보여주고 나머지는 갭 주변만
        header_end = node.body[0].lineno - 1 if node.body else node.lineno
        windows = [(start, max(start, header_end))]
        windows += _gap_windows(gaps, LONG_FUNCTION_CONTEXT_LINES, start, end)
    else:
        windows = [(start, end)]

    # 본문 중 실행된 라인이 하나도 없으면 테스트가 이 함수를 아예 호출하지 않은 것
    body_start = node.body[0].lineno if node.body else node.lineno
    never_called = executed is not None and not any(body_start <= line <= end for line in executed)

    return TestTarget(
        file=rel_path,
        qualname=qualname,
        start_line=start,
        signature=_build_signature(source_lines, node),
        source=_render_source(source_lines, windows, missing, partial),
        truncated=truncated,
        gaps=gaps,
        never_called=never_called,
        dependencies=_dependencies(node, symbols),
        module_name=module_name,
    )


def _targets_for_file(rel_path: str, abs_path: Path, file_report: dict, source_root: Path) -> list[TestTarget]:
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

    missing = set(file_report.get("missing_lines", []))
    # 오래된 coverage 형식에는 executed_lines가 없을 수 있다 → 구간 합치기·미호출 판정을 하지 않는다
    executed = set(file_report["executed_lines"]) if "executed_lines" in file_report else None
    # 출발 라인이 아예 실행되지 않은 분기는 버린다: 그 라인을 실행시키는 게 먼저이고,
    # 이미 line 갭으로 잡혀 있으므로 별도 갭으로 만들면 중복이다.
    branch_arcs = sorted(
        (src, dst) for src, dst in file_report.get("missing_branches", []) if src not in missing
    )
    partial = {src for src, _ in branch_arcs}
    missing_display = _missing_statement_lines(tree, missing)
    symbols = _module_symbols(tree, source_lines)
    module_name = _guess_module_name(rel_path, tree, source_root)

    # 같은 이름의 함수(예: @property 와 @x.setter)가 있을 수 있어 이름이 아니라 노드 기준으로 묶는다
    grouped: dict[int, tuple[str | None, ast.AST | None, list[CoverageGap]]] = {}

    def add(gap_line: int, make_gap) -> None:
        qualname, node = _enclosing_function(functions, gap_line)
        grouped.setdefault(id(node), (qualname, node, []))[2].append(make_gap(qualname))

    for start, end in _merge_line_ranges(_group_consecutive(list(missing)), executed, functions):
        add(start, lambda q, s=start, e=end: CoverageGap(rel_path, "line", s, e, q))
    for src, dst in branch_arcs:
        add(src, lambda q, s=src, d=dst: CoverageGap(rel_path, "branch", s, s, q, branch_target=d))

    # 최상위 함수/클래스의 범위. 모듈 레벨 갭의 문맥이 이 안으로 넘어가지 않게 한다
    function_spans = [
        (_def_start(n), n.end_lineno)
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]

    targets = []
    for qualname, node, target_gaps in grouped.values():
        target_gaps.sort(key=lambda g: (g.start_line, g.kind))
        targets.append(
            _build_target(
                rel_path, qualname, node, target_gaps, source_lines,
                missing_display, partial, function_spans, executed, symbols, module_name,
            )
        )
    targets.sort(key=lambda t: t.start_line)
    return targets


def extract_targets(coverage_json_path: Path, source_root: Path) -> list[TestTarget]:
    """coverage.json을 읽어 전체 파일의 TestTarget(함수 단위 갭 묶음) 목록을 만든다.

    coverage.json 안의 파일 경로는 source_root 기준 상대경로라고 가정한다
    (예: source_root=<target>/backend, "app/routers/attendance.py").
    """
    data = json.loads(Path(coverage_json_path).read_text(encoding="utf-8"))
    targets: list[TestTarget] = []

    for raw_path, file_report in data.get("files", {}).items():
        rel_path = _to_posix(raw_path)
        abs_path = (source_root / raw_path).resolve()
        targets.extend(_targets_for_file(rel_path, abs_path, file_report, source_root))

    return targets
