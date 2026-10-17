"""3단계: 테스트 케이스 설계 → pytest 코드 생성 → 대상 프로젝트에서 실행 → 판정 → 실패 피드백.

2단계까지는 "케이스 설계서"만 만들었다. 소형 모델의 설계에는 실행해 봐야만 드러나는 오류
(잘못된 mock 반환형, 필수 mock 누락, 일부 분기 누락)가 남으므로 실제 실행 결과로 판정하고,
실패 메시지와 아직 실행되지 않은 라인을 모델에 돌려줘 고치게 한다. 끝까지 실패하는 테스트는 제거하고
통과한 테스트만 대상 프로젝트에 남긴다.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

from testgen.llm_runner import LLMBackend
from testgen.models import LLMResponse, TestTarget

_CODE_FENCE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)
_MARKER_RE = re.compile(r"^(>>|B>|  ) ", re.MULTILINE)


# ── 대상 프로젝트의 테스트 환경 요약 ─────────────────────────────────────


@dataclass
class ProjectTestContext:
    fixtures: list[str] = field(default_factory=list)  # "client (scope=session): 설명"
    import_examples: list[str] = field(default_factory=list)  # 기존 테스트의 import 줄


def _is_fixture(decorator: ast.AST) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return ast.unparse(target) in ("pytest.fixture", "fixture")


def collect_project_context(source_root: Path, tests_dir: str = "tests") -> ProjectTestContext:
    """tests/conftest.py의 픽스처와 기존 테스트 파일의 import 방식을 모은다.
    실제 사례: 픽스처 이름을 몰라 모델이 "Session을 인메모리 DB로 mock" 같은 실행 불가능한 지시를 만들었다."""
    context = ProjectTestContext()
    conftest = source_root / tests_dir / "conftest.py"
    if conftest.is_file():
        tree = ast.parse(conftest.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [d for d in node.decorator_list if _is_fixture(d)]
            if not decorators:
                continue
            scope = ""
            for d in decorators:
                if isinstance(d, ast.Call):
                    for kw in d.keywords:
                        if kw.arg == "scope" and isinstance(kw.value, ast.Constant):
                            scope = f" (scope={kw.value.value})"
            params = [a.arg for a in node.args.args]
            doc = (ast.get_docstring(node) or "").strip().splitlines()
            detail = f" — {doc[0]}" if doc else ""
            uses = f" [의존: {', '.join(params)}]" if params else ""
            context.fixtures.append(f"{node.name}{scope}{uses}{detail}")

    seen = set()
    for test_file in sorted((source_root / tests_dir).glob("test_*.py"))[:5]:
        for line in test_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and stripped not in seen:
                seen.add(stripped)
                context.import_examples.append(stripped)
    context.import_examples = context.import_examples[:10]
    return context


# ── 프롬프트 ────────────────────────────────────────────────────────────


def _plain_source(target: TestTarget) -> str:
    """'>>', 'B>' 표시는 코드 생성에 필요 없으므로 떼고 라인 번호만 남긴다."""
    return _MARKER_RE.sub("   ", target.source)


def _cases_json(response: LLMResponse) -> str:
    return json.dumps(
        {"common_preconditions": response.common_preconditions, "test_cases": response.test_cases},
        ensure_ascii=False,
        indent=1,
    )


def _rules(target: TestTarget) -> str:
    module = target.module_name or "<대상 모듈>"
    package, _, leaf = module.rpartition(".")
    import_line = f"from {package} import {leaf}" if package else f"import {leaf}"
    return f"""작성 규칙:
1. 대상 모듈은 `{import_line}`로 import하세요. mock은 `patch.object({leaf}, "<이름>")` 또는 `patch("{module}.<이름>")`로 하세요.
   다른 경로(예: app.로 시작하는 경로)로 patch하면 같은 모듈이 다른 이름으로 다시 로드되어 mock이 적용되지 않습니다.
2. 외부 API·네트워크·현재 시각처럼 환경에 따라 달라지는 의존성은 반드시 mock하세요. 실제 네트워크 호출은 금지입니다.
3. mock 반환값은 코드가 그 값을 쓰는 방식에 맞는 타입으로 만드세요 (예: 반환값에 `.strftime()`을 호출하면 datetime 객체).
4. 함수 인자로 받는 DB 세션은 `MagicMock()`으로 만들고 코드가 쓰는 쿼리 체인의 결과만 지정해도 됩니다
   (예: `db.query.return_value.filter.return_value.all.return_value = [...]`). 레코드는 필요한 속성만 가진 객체(SimpleNamespace)로 충분합니다.
5. 케이스마다 테스트 함수를 만들고(이름: test_tc<번호>_<짧은_영문_설명>), docstring 첫 줄에 케이스 id를 쓰세요.
   입력만 다른 케이스(경계값 등)는 @pytest.mark.parametrize로 묶어도 됩니다.
6. 설계의 expected를 assert로 검증하세요. mock에 전달된 인자를 검증해야 하면 `mock.call_args`를 쓰세요.
7. 설계가 실제 코드와 맞지 않으면(잘못된 mock 대상·반환형, 필요 없는 mock 등) 코드에 맞게 고쳐 작성하고 짧은 주석으로 이유를 남기세요.
출력: 설명 없이 ```python 코드 블록 하나만 출력하세요 (파일 전체)."""


def build_codegen_prompt(
    target: TestTarget,
    response: LLMResponse,
    context: ProjectTestContext,
    test_rel_path: str,
    framework_hint: str | None,
) -> str:
    deps = "\n".join(f"- {d}" for d in target.dependencies) or "- (없음)"
    fixtures = "\n".join(f"- {f}" for f in context.fixtures) or "- (conftest.py 픽스처 없음)"
    imports = "\n".join(context.import_examples) or "(기존 테스트 없음)"
    return f"""당신은 pytest 테스트 코드를 작성하는 시니어 QA 엔지니어입니다.
아래 테스트 케이스 설계를 실행 가능한 pytest 테스트 파일 하나로 작성하세요.

대상: {target.qualname or '모듈 레벨 코드'} (파일 {target.file}, 테스트 실행 시 모듈 이름 `{target.module_name}`)
소스:
```python
{_plain_source(target)}
```

이 코드가 참조하는 모듈 수준 이름과 출처:
{deps}

테스트 케이스 설계:
```json
{_cases_json(response)}
```

테스트 환경:
- 작성한 파일은 `{test_rel_path}`에 저장되어 대상 프로젝트 루트에서 pytest로 실행됩니다 (tests/conftest.py가 적용됨)
- 기존 테스트의 import 예:
{imports}
- tests/conftest.py의 픽스처:
{fixtures}
- 프로젝트 설명: {framework_hint or 'pytest 기반 테스트 스위트.'}

{_rules(target)}
"""


def build_fix_prompt(target: TestTarget, code: str, result: "RunResult") -> str:
    failures = "\n".join(
        f"- {t.name}: {t.message[:600]}" for t in result.tests if t.outcome in ("failed", "error")
    ) or "- (없음)"
    collection = f"\n수집/import 오류:\n{result.collection_error[:1500]}\n" if result.collection_error else ""
    uncovered = (
        f"- 아직 실행되지 않은 대상 함수 라인: {result.uncovered_lines or '없음'}\n"
        f"- 아직 실행되지 않은 분기 (출발->도착, 음수는 함수 종료): {result.uncovered_branches or '없음'}"
    )
    return f"""아래 pytest 파일을 실행한 결과 문제가 있습니다. 문제를 고친 파일 전체를 다시 작성하세요.
통과한 테스트는 그대로 유지하고, 실패한 테스트와 빠진 경로만 고치거나 추가하세요.

대상: {target.qualname} (모듈 이름 `{target.module_name}`)
소스:
```python
{_plain_source(target)}
```

현재 파일:
```python
{code}
```

실행 결과:
{collection}실패한 테스트:
{failures}
{uncovered}

{_rules(target)}
"""


def extract_code(raw: str) -> tuple[str | None, str | None]:
    """모델 출력에서 파이썬 코드를 꺼내 문법을 검사한다. (코드, 오류) 중 하나만 채워진다."""
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    blocks = _CODE_FENCE_RE.findall(text)
    code = max(blocks, key=len).strip() if blocks else text.strip()
    if not code:
        return None, "모델 출력에 코드가 없습니다"
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return None, f"생성된 코드 문법 오류: {exc.msg} (라인 {exc.lineno})"
    return code + "\n", None


# ── 실행과 판정 ─────────────────────────────────────────────────────────


@dataclass
class TestOutcome:
    name: str  # 예: test_tc2_boundary[17999]
    outcome: str  # passed | failed | error | skipped
    message: str = ""
    classname: str = ""  # 수집 오류는 pytest가 빈 classname으로 기록한다


@dataclass
class RunResult:
    returncode: int
    tests: list[TestOutcome] = field(default_factory=list)
    collection_error: str = ""
    uncovered_lines: list[int] = field(default_factory=list)
    uncovered_branches: list[list[int]] = field(default_factory=list)
    function_statements: int = 0  # 대상 함수 범위의 실행 가능 라인 수
    output_tail: str = ""

    @property
    def passed(self) -> int:
        return sum(t.outcome == "passed" for t in self.tests)

    @property
    def failed(self) -> list[str]:
        return [t.name for t in self.tests if t.outcome in ("failed", "error")]

    @property
    def ok(self) -> bool:
        return not self.collection_error and not self.failed and self.passed > 0


def _parse_junit(path: Path) -> list[TestOutcome]:
    if not path.is_file():
        return []
    outcomes = []
    for case in ET.parse(path).getroot().iter("testcase"):
        outcome, message = "passed", ""
        for child in case:
            if child.tag in ("failure", "error", "skipped"):
                outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[child.tag]
                message = (child.get("message") or "") + "\n" + (child.text or "")
                break
        outcomes.append(TestOutcome(case.get("name", ""), outcome, message.strip(), case.get("classname", "")))
    return outcomes


def _function_coverage(coverage_json: Path, target: TestTarget) -> tuple[list[int], list[list[int]], int]:
    """새 실행에서 대상 함수 범위(start_line~end_line)에 남은 미실행 라인·분기."""
    if not coverage_json.is_file():
        return [], [], 0
    files = json.loads(coverage_json.read_text(encoding="utf-8")).get("files", {})
    report = next((v for k, v in files.items() if k.replace("\\", "/") == target.file), None)
    if report is None:
        return [], [], 0
    lo, hi = target.start_line, target.end_line or target.start_line
    missing = [n for n in report.get("missing_lines", []) if lo <= n <= hi]
    executed = [n for n in report.get("executed_lines", []) if lo <= n <= hi]
    branches = [b for b in report.get("missing_branches", []) if lo <= b[0] <= hi]
    return missing, branches, len(missing) + len(executed)


def run_tests(
    test_path: Path,
    source_root: Path,
    target: TestTarget,
    target_python: str,
    work_dir: Path,
    timeout: int,
) -> RunResult:
    """생성한 테스트 파일 하나만 대상 프로젝트의 Python으로 실행하고 커버리지를 측정한다."""
    work_dir.mkdir(parents=True, exist_ok=True)
    junit, cov_json = work_dir / "junit.xml", work_dir / "coverage.json"
    for stale in (junit, cov_json):
        stale.unlink(missing_ok=True)
    cov_source = Path(target.file).parts[0]
    command = [
        target_python, "-m", "pytest", str(test_path.relative_to(source_root)), "-q", "-p", "no:cacheprovider",
        f"--cov={cov_source}", "--cov-branch", f"--cov-report=json:{cov_json}", f"--junitxml={junit}",
    ]
    # .coverage 데이터 파일이 대상 프로젝트에 생기지 않도록 작업 폴더로 돌린다
    env = {**os.environ, "COVERAGE_FILE": str(work_dir / ".coverage")}
    try:
        proc = subprocess.run(
            command, cwd=source_root, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, env=env,
        )
        output, returncode = (proc.stdout or "") + (proc.stderr or ""), proc.returncode
    except subprocess.TimeoutExpired:
        return RunResult(returncode=-1, collection_error=f"pytest가 {timeout}초 안에 끝나지 않았습니다")
    except FileNotFoundError:
        return RunResult(returncode=-1, collection_error=f"대상 프로젝트 Python을 찾을 수 없습니다: {target_python}")

    tests = _parse_junit(junit)
    collection_error = ""
    if "no module named pytest_cov" in output.lower() or "unrecognized arguments: --cov" in output:
        collection_error = "대상 프로젝트 환경에 pytest-cov가 없습니다 (pip install pytest-cov)"
    elif returncode not in (0, 1) or (not tests and returncode != 0):
        # 2: 수집 오류/중단, 3: 내부 오류, 4: 사용법 오류, 5: 수집된 테스트 없음
        collection_error = output[-3000:]
    collection_cases = [t for t in tests if t.outcome == "error" and not t.classname]
    if collection_cases:
        collection_error = collection_cases[0].message[-3000:] or output[-3000:]
        tests = [t for t in tests if t not in collection_cases]

    missing, branches, statements = _function_coverage(cov_json, target)
    return RunResult(
        returncode=returncode, tests=tests, collection_error=collection_error,
        uncovered_lines=missing, uncovered_branches=branches, function_statements=statements,
        output_tail=output[-2000:],
    )


def prune_failing(code: str, failed: list[str]) -> str | None:
    """끝까지 실패한 테스트 함수를 제거한 코드. 남는 테스트가 없으면 None.
    parametrize된 테스트는 한 경우라도 실패하면 함수 전체를 제거한다 (부분 제거는 데코레이터 재작성이 필요)."""
    base_names = {name.split("[", 1)[0] for name in failed}
    tree = ast.parse(code)

    def keep(node: ast.stmt) -> bool:
        return not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in base_names)

    tree.body = [n for n in tree.body if keep(n)]
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            node.body = [n for n in node.body if keep(n)] or [ast.Pass()]
    remaining = [
        n.name for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")
    ]
    return ast.unparse(tree) + "\n" if remaining else None


# ── 전체 흐름 ──────────────────────────────────────────────────────────


@dataclass
class CodegenReport:
    target_id: str
    model: str
    function: str
    test_file: str | None  # 대상 프로젝트에 최종으로 남긴 파일 (없으면 None)
    status: str  # accepted | partial | rejected
    rounds: list[dict] = field(default_factory=list)
    final_passed: int = 0
    removed_tests: list[str] = field(default_factory=list)
    uncovered_lines: list[int] = field(default_factory=list)
    uncovered_branches: list[list[int]] = field(default_factory=list)
    function_statements: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_").lower() or "module"


def default_target_python(source_root: Path) -> str:
    """대상 프로젝트의 가상환경 Python을 찾는다 (Windows: .venv\\Scripts\\python.exe)."""
    for venv in (".venv", "venv", "env"):
        for candidate in (source_root / venv / "Scripts" / "python.exe", source_root / venv / "bin" / "python"):
            if candidate.is_file():
                return str(candidate)
    return sys.executable


def generate_and_run(
    target: TestTarget,
    response: LLMResponse,
    backend: LLMBackend,
    source_root: Path,
    output_dir: Path,
    target_python: str,
    context: ProjectTestContext,
    framework_hint: str | None = None,
    generated_dir: str = "tests/_ai_generated",
    fix_rounds: int = 2,
    timeout: int = 300,
    log=print,
) -> CodegenReport:
    """케이스 → 코드 생성 → 실행 → (실패 시 피드백 수정 반복) → 실패 테스트 제거 → 최종 판정."""
    rel_path = f"{generated_dir}/test_{_safe(target.qualname or 'module')}_{target.target_id}.py"
    test_path = source_root / rel_path
    test_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "codegen" / f"{target.target_id}__{backend.name}"
    work_dir.mkdir(parents=True, exist_ok=True)
    report = CodegenReport(target.target_id, backend.name, target.qualname or "<module>", None, "rejected")

    prompt = build_codegen_prompt(target, response, context, rel_path, framework_hint)
    code, result = None, None
    for round_no in range(fix_rounds + 1):
        (work_dir / f"prompt_{round_no}.txt").write_text(prompt, encoding="utf-8")
        llm = backend.run(target.target_id, prompt, structured=False)
        round_info = {"round": round_no, "elapsed_sec": round(llm.elapsed_sec, 1)}
        if not llm.ok:
            round_info["error"] = llm.error
            report.rounds.append(round_info)
            log(f"    [코드 {round_no}] LLM 호출 실패: {llm.error}")
            break
        new_code, code_error = extract_code(llm.raw_output)
        if code_error:
            round_info["error"] = code_error
            report.rounds.append(round_info)
            log(f"    [코드 {round_no}] {code_error}")
            if code is None:
                (work_dir / f"raw_{round_no}.txt").write_text(llm.raw_output, encoding="utf-8")
                prompt = prompt + f"\n\n직전 출력 문제: {code_error}. 실행 가능한 코드 블록 하나만 다시 출력하세요."
                continue
            break  # 이전 라운드 코드가 있으면 그것으로 마무리
        code = new_code
        (work_dir / f"code_{round_no}.py").write_text(code, encoding="utf-8")
        test_path.write_text(code, encoding="utf-8")
        result = run_tests(test_path, source_root, target, target_python, work_dir, timeout)
        round_info.update(
            passed=result.passed, failed=result.failed, collection_error=result.collection_error[:500],
            uncovered_lines=result.uncovered_lines, uncovered_branches=result.uncovered_branches,
        )
        report.rounds.append(round_info)
        log(
            f"    [코드 {round_no}] 통과 {result.passed} / 실패 {len(result.failed)}"
            + (" / 수집 오류" if result.collection_error else "")
            + f" / 함수 미실행 라인 {len(result.uncovered_lines)}개, 분기 {len(result.uncovered_branches)}개"
        )
        if result.ok and not result.uncovered_lines and not result.uncovered_branches:
            break
        if round_no < fix_rounds:
            prompt = build_fix_prompt(target, code, result)

    if code is None or result is None:
        test_path.unlink(missing_ok=True)
        report.note = "실행 가능한 코드를 얻지 못함"
        return report

    if result.collection_error:
        test_path.unlink(missing_ok=True)
        report.note = "수집/import 오류로 테스트를 실행하지 못함 — 대상 프로젝트에서 파일 제거"
        return report

    if result.failed:
        pruned = prune_failing(code, result.failed)
        if pruned is None:
            test_path.unlink(missing_ok=True)
            report.note = "모든 테스트가 실패 — 대상 프로젝트에서 파일 제거"
            report.removed_tests = result.failed
            return report
        test_path.write_text(pruned, encoding="utf-8")
        (work_dir / "code_pruned.py").write_text(pruned, encoding="utf-8")
        report.removed_tests = result.failed
        result = run_tests(test_path, source_root, target, target_python, work_dir, timeout)
        log(f"    [정리] 실패 테스트 {len(report.removed_tests)}개 제거 후 통과 {result.passed} / 실패 {len(result.failed)}")
        if not result.ok:
            test_path.unlink(missing_ok=True)
            report.note = "실패 테스트 제거 후에도 통과하지 않음 — 대상 프로젝트에서 파일 제거"
            return report

    report.test_file = rel_path
    report.final_passed = result.passed
    report.uncovered_lines = result.uncovered_lines
    report.uncovered_branches = result.uncovered_branches
    report.function_statements = result.function_statements
    fully_covered = not result.uncovered_lines and not result.uncovered_branches
    report.status = "accepted" if fully_covered and not report.removed_tests else "partial"
    return report
