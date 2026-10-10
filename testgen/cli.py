"""AI 기반 테스트케이스 생성 파이프라인 진입점 (1단계: 갭 추출·함수 단위 묶기, 2단계: LLM 생성 요청).

사용 예 (분석 대상 프로젝트에서 coverage.json을 먼저 만든 뒤):
    python -m testgen.cli \\
        --coverage-json "C:/Users/looky/Desktop/Test Develop Project/backend/coverage.json" \\
        --source-root "C:/Users/looky/Desktop/Test Develop Project/backend" \\
        --framework-hint "FastAPI + SQLAlchemy, tests/conftest.py의 TestClient/DB 세션 픽스처 사용" \\
        --limit 5

무과금 로컬 모델(Ollama 등 OpenAI 호환 API)을 쓰려면 --models local:<모델명> 으로 지정한다:
    --models local:<ornith 모델 태그>,local:qwen3:8b

갭 추출만 먼저 확인하고 싶으면 --dry-run 을 붙이면 LLM 호출 없이 targets.json과 프롬프트만 만든다.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from testgen.case_parser import TEST_CASES_SCHEMA, parse_test_cases
from testgen.config import DEFAULT_LOCAL_BASE_URL, DEFAULT_OUTPUT_DIR, LOCAL_API_KEY
from testgen.coverage_extractor import extract_targets
from testgen.llm_runner import build_backends
from testgen.models import TestTarget
from testgen.prompt_builder import build_prompt
from testgen.report import write_cases_csv


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--coverage-json", required=True, type=Path, help="분석 대상 프로젝트의 coverage.json 경로 (또는 그 파일이 있는 폴더)"
    )
    parser.add_argument("--source-root", required=True, type=Path, help="coverage.json 안의 파일 경로가 상대경로로 기록된 기준 루트")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="결과 저장 위치 (기본: ai-testgen/output)")
    parser.add_argument("--framework-hint", default=None, help="LLM 프롬프트에 넣을 대상 프로젝트/테스트 프레임워크 설명")
    parser.add_argument("--kind", choices=["all", "line", "branch"], default="all", help="추출할 갭 종류 필터")
    parser.add_argument("--file-contains", default=None, help="이 문자열을 포함하는 파일 경로의 갭만 처리")
    parser.add_argument(
        "--qualname", default=None, help="이 이름의 함수만 처리 (예: analyze_work_hours 또는 Class.method)"
    )
    parser.add_argument("--limit", type=int, default=None, help="처리할 대상 함수 개수 상한 (LLM 호출 비용 제어용)")
    parser.add_argument(
        "--models",
        default="claude,codex",
        help="호출할 모델 목록 (콤마 구분). claude, codex(유료 CLI) 또는 local:<모델명>(로컬 런타임, 무과금)",
    )
    parser.add_argument(
        "--local-base-url",
        default=DEFAULT_LOCAL_BASE_URL,
        help="local:<모델명>이 호출할 OpenAI 호환 API 기준 URL (기본: Ollama, 환경변수 TESTGEN_LOCAL_BASE_URL)",
    )
    parser.add_argument("--workers", type=int, default=4, help="LLM 호출 동시 실행 개수")
    parser.add_argument("--dry-run", action="store_true", help="갭 추출과 프롬프트 생성만 하고 LLM은 호출하지 않음")
    return parser.parse_args(argv)


def filter_targets(
    targets: list[TestTarget],
    kind: str,
    file_contains: str | None,
    limit: int | None,
    qualname: str | None = None,
) -> list[TestTarget]:
    filtered = targets
    if qualname:
        # 전체 이름(Class.method) 또는 마지막 이름(method)이 일치하는 대상만
        filtered = [
            t for t in filtered if t.qualname and qualname in (t.qualname, t.qualname.rsplit(".", 1)[-1])
        ]
    if kind != "all":
        # 해당 종류의 갭만 남기고, 남은 갭이 없는 대상은 제외한다
        filtered = [replace(t, gaps=[g for g in t.gaps if g.kind == kind]) for t in filtered]
        filtered = [t for t in filtered if t.gaps]
    if file_contains:
        filtered = [t for t in filtered if file_contains in t.file]
    if limit is not None:
        filtered = filtered[:limit]
    return filtered


def resolve_coverage_json(path: Path) -> Path | None:
    """--coverage-json에 폴더를 넘긴 경우 그 안의 coverage.json을 쓴다. 못 찾으면 None."""
    if path.is_file():
        return path
    if path.is_dir() and (path / "coverage.json").is_file():
        return path / "coverage.json"
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    coverage_json = resolve_coverage_json(args.coverage_json)
    if coverage_json is None:
        if args.coverage_json.is_dir():
            print(f"[오류] 폴더 안에 coverage.json이 없습니다: {args.coverage_json}", file=sys.stderr)
        else:
            print(f"[오류] coverage.json을 찾을 수 없습니다: {args.coverage_json}", file=sys.stderr)
        print("--coverage-json에는 coverage.json 파일 경로(또는 그 파일이 있는 폴더)를 넣으세요.", file=sys.stderr)
        print("아직 만들지 않았다면 대상 프로젝트에서 다음을 실행하세요:", file=sys.stderr)
        print("  python -m pytest tests/ --cov=app --cov-branch --cov-report=json:coverage.json", file=sys.stderr)
        return 1
    if coverage_json != args.coverage_json:
        print(f"  --coverage-json이 폴더라서 그 안의 파일을 사용합니다: {coverage_json}")
    args.coverage_json = coverage_json
    if not args.source_root.is_dir():
        print(f"[오류] source-root 디렉터리가 없습니다: {args.source_root}", file=sys.stderr)
        return 1

    print(f"[1/2] 커버리지 갭 추출 중... ({args.coverage_json})")
    all_targets = extract_targets(args.coverage_json, args.source_root)
    targets = filter_targets(all_targets, args.kind, args.file_contains, args.limit, args.qualname)
    total_gaps = sum(len(t.gaps) for t in all_targets)
    selected_gaps = sum(len(t.gaps) for t in targets)
    print(f"  전체 갭 {total_gaps}개 → 대상 함수 {len(all_targets)}개로 묶음")
    if not all_targets:
        print(
            "  [주의] 추출된 갭이 없습니다. 커버리지가 100%가 아니라면 --source-root가 맞는지 확인하세요 "
            "(coverage.json 안의 파일 경로, 예: app/main.py 가 source-root 기준으로 존재해야 함).",
            file=sys.stderr,
        )
    print(
        f"  그중 대상 {len(targets)}개(갭 {selected_gaps}개) 선택 "
        f"(kind={args.kind}, file_contains={args.file_contains}, qualname={args.qualname}, limit={args.limit})"
    )

    output_dir: Path = args.output_dir
    targets_file = output_dir / "targets.json"
    prompts_dir = output_dir / "prompts"
    responses_dir = output_dir / "responses"
    for d in (output_dir, prompts_dir, responses_dir):
        d.mkdir(parents=True, exist_ok=True)

    targets_file.write_text(
        json.dumps([t.to_dict() for t in targets], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  대상 목록 저장: {targets_file}")

    prompts: dict[str, str] = {}
    for target in targets:
        prompt = build_prompt(target, args.framework_hint)
        prompts[target.target_id] = prompt
        (prompts_dir / f"{target.target_id}.txt").write_text(prompt, encoding="utf-8")

    if args.dry_run or not targets:
        print("dry-run 모드라 LLM 호출을 건너뜁니다." if args.dry_run else "처리할 대상이 없습니다.")
        return 0

    model_specs = [m.strip() for m in args.models.split(",") if m.strip()]
    try:
        runners = build_backends(model_specs, args.local_base_url, TEST_CASES_SCHEMA, LOCAL_API_KEY)
    except ValueError as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 1
    model_names = [runner.name for runner in runners]

    print(
        f"[2/2] 대상 {len(targets)}개 x 모델 {len(runners)}개 = {len(targets) * len(runners)}건 "
        f"LLM 호출 시작 (workers={args.workers})"
    )

    jobs = [(runner, target) for target in targets for runner in runners]
    results = {name: {"ok": 0, "fail": 0, "unparsed": 0, "cases": 0} for name in model_names}

    def _run_job(job):
        runner, target = job
        response = runner.run(target.target_id, prompts[target.target_id])
        if response.ok:
            parsed = parse_test_cases(response.raw_output)
            response.test_cases = parsed.test_cases
            response.parse_errors = parsed.errors
        out_path = responses_dir / f"{target.target_id}__{runner.name}.json"
        out_path.write_text(json.dumps(response.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return target, response

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_run_job, job) for job in jobs]
        finished = []
        for i, future in enumerate(as_completed(futures), start=1):
            target, response = future.result()
            finished.append((target, response))
            r = results[response.model]
            if not response.ok:
                status = f"FAIL ({response.error})"
                r["fail"] += 1
            elif not response.test_cases:
                status = f"PARSE FAIL ({'; '.join(response.parse_errors[:2])})"
                r["unparsed"] += 1
            else:
                status = f"OK, 케이스 {len(response.test_cases)}개"
                if response.parse_errors:
                    status += f" (버림 {len(response.parse_errors)}건)"
                r["ok"] += 1
                r["cases"] += len(response.test_cases)
            print(f"  [{i}/{len(jobs)}] {response.model} / 대상 {response.target_id}: {status} ({response.elapsed_sec:.1f}s)")

    print("\n=== 요약 ===")
    for name in model_names:
        r = results[name]
        print(f"  {name}: 성공 {r['ok']}건 (케이스 {r['cases']}개) / 파싱 실패 {r['unparsed']}건 / 호출 실패 {r['fail']}건")
    print(f"응답 파일 저장 위치: {responses_dir}")
    cases_csv = output_dir / "test_cases.csv"
    written = write_cases_csv(finished, cases_csv)
    print(f"생성된 테스트 케이스 {written}개 모아보기 (엑셀로 열기): {cases_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
