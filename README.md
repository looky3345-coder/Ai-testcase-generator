# ai-testgen

커버리지 갭을 타겟팅하는 AI 기반 테스트케이스 생성 파이프라인.

분석 대상 프로젝트와는 완전히 독립된 도구다. 대상 프로젝트의 `coverage.json`과
소스 루트 경로를 CLI 인자로 받아 동작하며, 대상 프로젝트의 코드를 임포트하지 않는다.

## 전체 구조 (계획)

1. **커버리지 갭 추출** — pytest-cov `coverage.json`에서 미커버 라인/분기(방향 포함)를 찾아
   **함수 단위로 묶고** 함수 전체 소스와 함께 추출 (구현 완료: `testgen/coverage_extractor.py`)
2. **듀얼 LLM 테스트케이스 생성** — 두 모델에 ISTQB 기법(경계값 분석, 동등분할) 기반
   테스트 케이스를 요청하고, 응답 JSON을 스키마로 검증 (구현 완료: `testgen/prompt_builder.py`,
   `testgen/llm_runner.py`, `testgen/case_parser.py`, `testgen/cli.py`)
   - 무과금 로컬 모델(Ollama 등 OpenAI 호환 API, 예: Ornith) 또는 유료 CLI(`claude -p`, `codex exec`) 선택
3. **교차검증** — 두 모델 결과 중 공통 케이스를 신뢰도 높음으로 분류 (미구현)
4. **CSV 변환 + 실행** — 케이스를 CSV로 변환해 기존 pytest 프레임워크로 실행 (미구현)
5. **피드백 루프** — 실패 로그를 다시 LLM에 넣어 추가 엣지케이스 제안 (미구현)

## 개발 히스토리

변경 이력과 설계 결정은 [`docs/HISTORY.md`](docs/HISTORY.md),
[`docs/decisions/`](docs/decisions/), [`docs/reviews/`](docs/reviews/)에 기록한다 (규칙: [`CLAUDE.md`](CLAUDE.md)).

## 요구사항

- Python 3.9+ (표준 라이브러리만 사용, pip 설치 불필요)
- 아래 중 사용할 LLM 백엔드
- **(무과금, 권장)** OpenAI 호환 API를 제공하는 로컬 런타임 — 기본은 [Ollama](https://ollama.com)
  (`http://localhost:11434/v1`). llama.cpp server, LM Studio, vLLM도 `--local-base-url`로 사용 가능
- (유료) `claude` CLI (PATH에 있어야 함, `claude -p` 비대화형 모드로 호출)
- `codex` CLI (PATH에 있어야 함, `codex exec -` 비대화형 모드 + stdin 프롬프트로 호출.
  `npm install -g @openai/codex`로 설치 — 미설치 시 해당 모델만 실패로 기록되고 파이프라인은 계속 진행)

## 현재 상태 (2026-10-10)

- 갭을 함수 단위로 묶어 LLM 호출 (함수 전체 + 분기 방향 제공). 출력이 `targets.json`으로 바뀜
- 로컬 LLM 백엔드(OpenAI 호환 API) + JSON 스키마 출력 강제 + 응답 검증 추가.
  가짜 서버로 단위/통합 테스트 완료. **실제 로컬 모델로의 호출은 아직 미검증** (아래 "로컬 모델 사용법"의 스모크 테스트 필요)
- 이하는 2026-09-14 기준 기록 (경위는 [`docs/HISTORY.md`](docs/HISTORY.md))

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
- `--qualname <이름>` : 특정 함수만 처리 (예: `analyze_work_hours`, `Class.method`). LLM 실호출을 1개로 시작할 때 유용
- `--models claude` : 한쪽 모델만 호출 (`claude`, `codex`, `local:<모델명>` 콤마 구분)
- `--local-base-url <url>` : 로컬 런타임 주소 (기본 Ollama, 환경변수 `TESTGEN_LOCAL_BASE_URL`)
- `--limit N` : 처리할 대상 함수 개수 상한 (LLM 호출은 비용이 드므로 먼저 소규모로 테스트 권장)

결과는 `output/` 아래에 저장된다 (git에서 제외됨):

- `output/targets.json` — 대상 함수 목록 (함수별 소스 + 그 안의 갭: 미실행 라인 구간, 미실행 분기 `start_line → branch_target`,
  `never_called`: 테스트가 한 번도 호출하지 않은 함수, `dependencies`: 함수가 참조하는 모듈 수준 이름과 import 출처,
  `module_name`: 테스트 실행 시 import되는 모듈 이름 추정 — mock.patch 경로용)
- `output/prompts/<target_id>.txt` — 대상별로 실제 전송한 프롬프트
- `output/responses/<target_id>__<model>.json` — 모델별 원본 응답 + 성공/실패/소요시간
  + 스키마 검증을 통과한 `test_cases`와 버린 사유 `parse_errors`
- `output/test_cases.csv` — **생성된 테스트 케이스 전체 모아보기** (한 줄에 케이스 하나, 엑셀로 바로 열림).
  LLM 실행 시에만 생성되며 dry-run에서는 만들어지지 않음

### 로컬 모델 사용법 (무과금)

설치부터 GPU 확인까지 단계별 가이드: [`docs/local-llm-setup.md`](docs/local-llm-setup.md)

```bash
ollama pull <모델 태그>          # 예: Ornith 또는 qwen3 계열. 태그는 `ollama list`로 확인
ollama serve                     # 이미 실행 중이면 생략

python -m testgen.cli \
  --coverage-json "../Test Develop Project/backend/coverage.json" \
  --source-root "../Test Develop Project/backend" \
  --models "local:<모델 A>,local:<모델 B>" \
  --limit 3
```

- 서로 다른 계열의 로컬 모델 2개를 지정하면 무과금으로 듀얼 생성(교차검증용)이 된다.
- 요청에 JSON 스키마(`response_format`)를 함께 보내 출력 형식을 강제한다.
  런타임이 이를 지원하지 않으면 무시되고, 응답 검증 단계에서 형식 오류가 `PARSE FAIL`로 집계된다.
- 로컬 CPU 추론은 느리므로 호출 타임아웃은 600초(`testgen/config.py`)이고, `--workers 1`부터 시작하길 권장.

## 문제 해결

### coverage.json 생성 단계에서 `ImportError while loading conftest ... ModuleNotFoundError`

이 도구가 아니라 **대상 프로젝트의 의존성이 현재 Python 환경에 없다**는 뜻이다
(예: `No module named 'groq'`). 대상 프로젝트 폴더에서 그 프로젝트의 가상환경을 켜고 의존성을 설치한 뒤 다시 실행한다.

```powershell
cd <대상 프로젝트>\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pytest pytest-cov
python -m pytest tests/ --cov=app --cov-branch --cov-report=json:coverage.json
```

- 이 도구(`testgen`)는 표준 라이브러리만 쓰므로 대상 프로젝트 가상환경 안에서 실행해도, 밖에서 실행해도 된다.
- 테스트 일부가 실패해도 `coverage.json`은 만들어진다. 갭 추출에는 문제없다.

### coverage.json 생성 단계에서 `GroqError: The api_key client option must be set ...` (또는 다른 API 키 오류)

대상 프로젝트가 모듈 import 시점에 외부 API 클라이언트를 만들면서 키를 요구하는 경우다.
커버리지 측정에는 **가짜 키**를 환경변수로 넣는다 (실제 키는 API 호출 비용·비결정적 결과 때문에 권장하지 않음).

```powershell
$env:GROQ_API_KEY = "dummy-key-for-coverage"   # 현재 PowerShell 창에서만 유효
python -m pytest tests/ --cov=app --cov-branch --cov-report=json:coverage.json
```

- 실제 API를 호출하는 테스트는 인증 오류로 실패할 수 있지만 `coverage.json`은 생성된다 (해당 경로는 미커버 갭으로 잡힘).
- 대상 프로젝트에 `.env.example` 등이 있으면 다른 필수 환경변수도 확인한다.

## 테스트

```bash
python -m unittest discover -s tests -t .
```
