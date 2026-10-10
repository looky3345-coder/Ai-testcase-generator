# ai-testgen

커버리지 갭을 타겟팅하는 AI 기반 테스트케이스 생성 파이프라인.

분석 대상 프로젝트와는 완전히 독립된 도구다. 대상 프로젝트의 `coverage.json`과
소스 루트 경로를 CLI 인자로 받아 동작하며, 대상 프로젝트의 코드를 임포트하지 않는다.

## 전체 구조 (계획)

1. **커버리지 갭 추출** — pytest-cov `coverage.json`에서 미커버 라인/분기를 찾아
   해당 함수의 소스 스니펫과 함께 추출 (구현 완료: `testgen/coverage_extractor.py`)
2. **듀얼 LLM 테스트케이스 생성** — `claude -p`, `codex -p` 양쪽에 ISTQB 기법
   (경계값 분석, 동등분할) 기반 테스트 케이스를 요청 (구현 완료: `testgen/prompt_builder.py`,
   `testgen/llm_runner.py`, `testgen/cli.py`)
3. **교차검증** — 두 모델 결과 중 공통 케이스를 신뢰도 높음으로 분류 (미구현)
4. **CSV 변환 + 실행** — 케이스를 CSV로 변환해 기존 pytest 프레임워크로 실행 (미구현)
5. **피드백 루프** — 실패 로그를 다시 LLM에 넣어 추가 엣지케이스 제안 (미구현)

## 개발 히스토리

변경 이력과 설계 결정은 [`docs/HISTORY.md`](docs/HISTORY.md),
[`docs/decisions/`](docs/decisions/), [`docs/reviews/`](docs/reviews/)에 기록한다 (규칙: [`CLAUDE.md`](CLAUDE.md)).

## 요구사항

- Python 3.9+ (표준 라이브러리만 사용, pip 설치 불필요)
- `claude` CLI (PATH에 있어야 함, `claude -p` 비대화형 모드로 호출)
- `codex` CLI (PATH에 있어야 함, `codex exec -` 비대화형 모드 + stdin 프롬프트로 호출.
  `npm install -g @openai/codex`로 설치 — 미설치 시 해당 모델만 실패로 기록되고 파이프라인은 계속 진행)

## 현재 상태 (2026-09-14)

- 1~2단계 구현 완료. 실제 backend `coverage.json`(전체 커버리지 50.25%)으로 검증 —
  339개 갭(라인 250 + 브랜치 89) 추출, 함수/클래스 중첩 매핑과 스니펫 생성 정상 확인
- `claude -p` 서브프로세스 호출 자체는 정상 동작 확인. 단, 이 머신의 `claude` CLI 세션이
  만료된 상태(`401 OAuth access token has expired`) — 실제 응답을 받으려면 `claude login` 재인증 필요
- `codex` CLI는 이 머신에 미설치. 비대화형 커맨드를 `codex -p`로 잘못 추측했던 걸
  공식 문서로 확인해 `codex exec -`로 수정함 (`testgen/config.py`)
- **보류 중:** codex 과금 방식(무료 체험은 제한적 / Plus 월 $20 구독 / API 키 pay-as-you-go 중
  선택) — 예산 계획이 구체화되지 않아 이번 세션에서는 실제 설치·인증까지는 진행하지 않음.
  파이프라인 자체(1~2단계 코드, `--dry-run`)는 LLM 호출 없이도 갭 추출까지는 확인 가능한 상태
- **다음 작업:** codex 설치/인증 방식 결정 후 소규모(`--limit`)로 듀얼 LLM 실호출 테스트,
  이어서 3단계(교차검증) 구현

## 사용법

먼저 분석 대상 프로젝트에서 커버리지 리포트를 생성한다 (예: 이 저장소의
`Test Develop Project/backend`):

```bash
python -m pytest tests/ --cov=app --cov-branch --cov-report=json:coverage.json
```

그다음 이 도구를 실행한다 (`ai-testgen/` 디렉터리에서):

```bash
python -m testgen.cli \
  --coverage-json "../Test Develop Project/backend/coverage.json" \
  --source-root "../Test Develop Project/backend" \
  --framework-hint "FastAPI + SQLAlchemy, tests/conftest.py의 TestClient/DB 세션 픽스처 사용" \
  --limit 5
```

주요 옵션:

- `--dry-run` : LLM 호출 없이 갭 추출 + 프롬프트 생성까지만 실행
- `--kind line|branch|all` : 갭 종류 필터
- `--file-contains <substr>` : 특정 파일/디렉터리만 처리
- `--models claude` : 한쪽 모델만 호출
- `--limit N` : 처리할 갭 개수 상한 (LLM 호출은 비용이 드므로 먼저 소규모로 테스트 권장)

결과는 `output/` 아래에 저장된다 (git에서 제외됨):

- `output/gaps.json` — 추출된 갭 전체 목록
- `output/prompts/<gap_id>.txt` — 갭별로 실제 전송한 프롬프트
- `output/responses/<gap_id>__<model>.json` — 모델별 원본 응답 + 성공/실패/소요시간
