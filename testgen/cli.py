"""AI 기반 테스트케이스 생성 파이프라인 진입점 (1단계: 갭 추출, 2단계: LLM 생성 요청).

사용 예 (분석 대상 프로젝트에서 coverage.json을 먼저 만든 뒤):
    python -m testgen.cli \\
        --coverage-json "C:/Users/looky/Desktop/Test Develop Project/backend/coverage.json" \\
        --source-root "C:/Users/looky/Desktop/Test Develop Project/backend" \\
        --framework-hint "FastAPI + SQLAlchemy, tests/conftest.py의 TestClient/DB 세션 픽스처 사용" \\
        --limit 5

갭 추출만 먼저 확인하고 싶으면 --dry-run 을 붙이면 LLM 호출 없이 gaps.json만 만든다.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from testgen.config import (
    DEFAULT_GAPS_FILE,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROMPTS_DIR,
    DEFAULT_RESPONSES_DIR,
    LLM_RUNNERS,
)
from testgen.coverage_extractor import extract_gaps
from testgen.llm_runner import LLMRunner
from testgen.models import CoverageGap
from testgen.prompt_builder import build_prompt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--coverage-json", required=True, type=Path, help="분석 대상 프로젝트의 coverage.json 경로")
    parser.add_argument("--source-root", required=True, type=Path, help="coverage.json 안의 파일 경로가 상대경로로 기록된 기준 루트")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="결과 저장 위치 (기본: ai-testgen/output)")
    parser.add_argument("--framework-hint", default=None, help="LLM 프롬프트에 넣을 대상 프로젝트/테스트 프레임워크 설명")
    parser.add_argument("--kind", choices=["all", "line", "branch"], default="all", help="추출할 갭 종류 필터")
    parser.add_argument("--file-contains", default=None, help="이 문자열을 포함하는 파일 경로의 갭만 처리")
    parser.add_argument("--limit", type=int, default=None, help="처리할 갭 개수 상한 (LLM 호출 비용 제어용)")
    parser.add_argument("--models", default="claude,codex", help="호출할 모델 목록 (콤마 구분, testgen.config.LLM_RUNNERS 키)")
    parser.add_argument("--workers", type=int, default=4, help="LLM 호출 동시 실행 개수")
    parser.add_argument("--dry-run", action="store_true", help="갭 추출과 프롬프트 생성만 하고 LLM은 호출하지 않음")
    return parser.parse_args(argv)


def filter_gaps(gaps: list[CoverageGap], kind: str, file_contains: str | None, limit: int | None) -> list[CoverageGap]:
    filtered = gaps
    if kind != "all":
        filtered = [g for g in filtered if g.kind == kind]
    if file_contains:
        filtered = [g for g in filtered if file_contains in g.file]
    if limit is not None:
        filtered = filtered[:limit]
    return filtered


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.coverage_json.is_file():
        print(f"[오류] coverage.json을 찾을 수 없습니다: {args.coverage_json}", file=sys.stderr)
        print("먼저 대상 프로젝트에서 다음을 실행하세요:", file=sys.stderr)
        print("  python -m pytest tests/ --cov=app --cov-branch --cov-report=json:coverage.json", file=sys.stderr)
        return 1
    if not args.source_root.is_dir():
        print(f"[오류] source-root 디렉터리가 없습니다: {args.source_root}", file=sys.stderr)
        return 1

    print(f"[1/2] 커버리지 갭 추출 중... ({args.coverage_json})")
    all_gaps = extract_gaps(args.coverage_json, args.source_root)
    gaps = filter_gaps(all_gaps, args.kind, args.file_contains, args.limit)
    print(f"  전체 갭 {len(all_gaps)}개 중 {len(gaps)}개 선택 (kind={args.kind}, file_contains={args.file_contains}, limit={args.limit})")

    output_dir: Path = args.output_dir
    gaps_file = output_dir / "gaps.json"
    prompts_dir = output_dir / "prompts"
    responses_dir = output_dir / "responses"
    for d in (output_dir, prompts_dir, responses_dir):
        d.mkdir(parents=True, exist_ok=True)

    gaps_file.write_text(
        json.dumps([g.to_dict() for g in gaps], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  갭 목록 저장: {gaps_file}")

    prompts: dict[str, str] = {}
    for gap in gaps:
        prompt = build_prompt(gap, args.framework_hint)
        prompts[gap.gap_id] = prompt
        (prompts_dir / f"{gap.gap_id}.txt").write_text(prompt, encoding="utf-8")

    if args.dry_run or not gaps:
        print("dry-run 모드이거나 처리할 갭이 없어 LLM 호출을 건너뜁니다." if args.dry_run else "처리할 갭이 없습니다.")
        return 0

    model_names = [m.strip() for m in args.models.split(",") if m.strip()]
    unknown = [m for m in model_names if m not in LLM_RUNNERS]
    if unknown:
        print(f"[오류] testgen.config.LLM_RUNNERS에 없는 모델: {unknown}", file=sys.stderr)
        return 1
    runners = [LLMRunner(name, LLM_RUNNERS[name]) for name in model_names]

    print(f"[2/2] {len(gaps)}개 갭 x {len(runners)}개 모델 = {len(gaps) * len(runners)}건 LLM 호출 시작 (workers={args.workers})")

    jobs = [(runner, gap) for gap in gaps for runner in runners]
    results = {name: {"ok": 0, "fail": 0} for name in model_names}

    def _run_job(job):
        runner, gap = job
        response = runner.run(gap.gap_id, prompts[gap.gap_id])
        out_path = responses_dir / f"{gap.gap_id}__{runner.name}.json"
        out_path.write_text(json.dumps(response.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return response

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_run_job, job) for job in jobs]
        for i, future in enumerate(as_completed(futures), start=1):
            response = future.result()
            status = "OK" if response.ok else f"FAIL ({response.error})"
            results[response.model]["ok" if response.ok else "fail"] += 1
            print(f"  [{i}/{len(jobs)}] {response.model} / gap {response.gap_id}: {status} ({response.elapsed_sec:.1f}s)")

    print("\n=== 요약 ===")
    for name in model_names:
        r = results[name]
        print(f"  {name}: 성공 {r['ok']}건 / 실패 {r['fail']}건")
    print(f"응답 파일 저장 위치: {responses_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
