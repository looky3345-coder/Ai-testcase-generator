# 개발 히스토리

최신 항목이 위. 규칙은 루트 `CLAUDE.md` 참고.

## 2026-10-10 — 프롬프트 개선 결과 실제 프로젝트에서 확인

**배경**
- 직전 항목에서 "미검증"으로 남긴 개선된 프롬프트를 사용자가 실제 프로젝트에서 재생성해 공유

**과정**
- 이전/현재 `analyze_work_hours` 프롬프트 비교: 쪼개짐 해소(6→1), 미호출 안내, 이어지는 줄 표시,
  의존성 목록, mock 지시, `--framework-hint` 반영 모두 확인
- 새 발견: 대상 프로젝트가 `app.` 없이 import(`from services.slack_service import ...`) →
  patch 경로 모호성(리뷰 6번)의 실제 근거 확보. 다음 개선 후보로 지정
- 대상 프로젝트 자체의 참고 사항(미사용 변수, 로그 문구 불일치)은 사용자에게 전달만 함

**변경**
- 문서만: 리뷰 문서에 "후속 확인" 섹션 추가, 본 항목. 코드 변경 없음

**검증**
- 실제 프로젝트 프롬프트 1건으로 확인 (사용자 공유). 전체 대상 수 변화(갭 267→?)는 아직 받지 못함 (**미확인**)
- LLM 응답 품질은 아직 미검증

**다음**
- 전체 요약 줄(갭/대상 수) 확인
- patch 경로 힌트: 대상 파일의 import 방식으로 실제 모듈 이름을 추정해 프롬프트에 제시
- 특정 함수만 골라 실행하는 필터(예: `--qualname`) — LLM 실호출을 이 함수 1개로 시작하기 위해

## 2026-10-10 — 실제 프롬프트 검토 반영: 쪼개진 갭 합치기, 미호출 함수 표시, 의존성 목록

**배경**
- 사용자가 실제 프로젝트 dry-run 프롬프트(`ai_service.py::analyze_work_hours`)를 공유
- 검토 결과 7가지 문제 발견 → [리뷰 문서](reviews/2026-10-10-first-real-prompt-review.md)
- 사용자 질문: "prompts 폴더 최상단이 먼저 생긴 파일인가?" → 아님. 파일명이 해시라 정렬 의미 없음,
  처리 순서는 `targets.json`. 분기 갭 많은 순으로 고르는 명령을 안내 (파일명 가독성 개선은 제안만 하고 보류)

**과정**
- 같은 구조의 모듈을 만들어 실제 pytest-cov 출력으로 재현: coverage.py는 **여러 줄 문장의 이어지는 줄과 빈 줄을
  `missing_lines`에 넣지 않으므로**, 연속 번호로만 묶던 기존 방식은 한 번도 호출되지 않은 함수를 여러 조각으로 나눴음
- 합치는 기준을 "번호가 연속"에서 "사이에 실행된 라인이 없음(`executed_lines` 이용)"으로 변경.
  단, 모듈 전체가 미실행인 경우 함수 경계를 넘어 합쳐지지 않도록 같은 함수끼리만 합침
- 미실행 표시는 AST 문장 범위로 확장. 복합문(if/try)은 머리가 미실행이면 본문도 미실행이므로 범위 확장이 안전함을 확인
- 테스트 작성 중 테스트 클래스 상속으로 부모 테스트가 중복 실행(35개)되는 실수 → 공통 setUp 베이스로 분리(29개)

**변경**
- `testgen/coverage_extractor.py`: `_merge_line_ranges`, `_missing_statement_lines`, `_module_symbols`, `_dependencies` 추가
- `testgen/models.py`: `TestTarget.never_called`, `TestTarget.dependencies` (targets.json에도 출력)
- `testgen/prompt_builder.py`: 미호출 함수 안내, "참조하는 모듈 수준 이름과 출처" 목록, mock/patch 지시(5번) 추가
- 사용자 영향: 같은 coverage.json이어도 갭 수가 줄고(조각 합침) 프롬프트가 길어짐(의존성 목록)

**검증**
- 단위 테스트 29개 통과 (신규 5개: 미호출 함수 재현 픽스처 `tests/fixtures/sample_project/app/ai_service.py`)
- 재현 모듈 dry-run: 갭 5조각 → 1개, 이어지는 줄 표시, 의존성 3개 출력 확인
- **미검증**: 실제 프로젝트에서 갭/대상 수 변화와 개선된 프롬프트 — 사용자 재실행 필요.
  개선된 프롬프트로 실제 LLM 응답 품질이 나아지는지는 아직 모름

**다음**
- 사용자 PC에서 최신 코드로 dry-run 재실행 → 같은 함수의 프롬프트 비교
- `--framework-hint`에 conftest 픽스처 정보 넣기 (리뷰 5번), patch 경로 문제(6번)는 3단계에서 실행으로 검증

## 2026-10-10 — 실제 대상 프로젝트 dry-run 첫 성공 + `--coverage-json` 경로 처리 개선

**배경**
- 가짜 `GROQ_API_KEY`로 대상 프로젝트(`Checkine-Automation-Project/backend`)의 coverage.json 생성 성공
- 이어서 dry-run을 실행했으나 `[오류] coverage.json을 찾을 수 없습니다: ...\backend` 발생

**과정**
- 원인: `--coverage-json`에 파일(`...\backend\coverage.json`)이 아니라 폴더(`...\backend`)를 넘김.
  기존 오류 메시지가 "파일이 없다"고만 해서 파일이 이미 있는 사용자에게는 원인이 보이지 않았음
- 같은 실수가 반복되기 쉬우므로 도구에서 흡수하기로 함: 폴더를 받으면 그 안의 coverage.json 사용
- 비슷한 경로 실수로 `--source-root`가 틀리면 파일을 조용히 건너뛰어 "갭 0개"가 되는 문제도 함께 확인 → 경고 추가
- 사용자가 파일 경로로 바로잡아 재실행 → 성공

**변경**
- `testgen/cli.py`: `resolve_coverage_json()` — 폴더 입력 시 내부 `coverage.json` 자동 사용(안내 출력),
  폴더/파일 각각 구체적인 오류 메시지. 추출 결과가 0개면 `--source-root` 확인 경고
- `tests/test_cli.py` (신규): 위 세 경우 테스트

**검증**
- 단위 테스트 24개 통과 (신규 3개)
- **실제 프로젝트 dry-run 결과 (사용자 PC)**: 갭 267개 → 대상 함수 107개
  - LLM 호출 수(모델 2개 기준): 갭 단위였다면 534회 → 함수 단위 214회
  - 참고: 2026-09-14 기록의 "갭 339개"는 다른 시점의 coverage.json(당시 테스트 실행 환경·이전 추출 방식) 기준이라 직접 비교 불가
- 경로 처리 개선 자체는 사용자 PC에서 아직 확인하지 않음 (사용자는 경로를 직접 고쳐 실행함)
- 생성된 프롬프트의 품질은 아직 검토 전

**다음**
- `output/prompts/` 샘플을 받아 프롬프트 검토·개선
- 대상 107개 중 크기 분포 확인 (잘린 함수 `truncated` 비율, 갭이 많은 함수) → 로컬 모델 컨텍스트 한계 점검
- 로컬 모델 `--limit 3` 스모크 테스트

## 2026-10-10 — 실제 대상 프로젝트 실행 시도 (2): import 시점 API 키 요구

**배경**
- 직전 항목의 조치(대상 프로젝트 `.venv` 생성, 의존성 설치)로 `groq` import 오류는 해결됨
- 그 과정에서 사용자가 PowerShell 가상환경 활성화(`Activate.ps1`) 사용법을 질문 → 실행 정책 오류/경로/cmd 차이를 안내

**과정**
- 재실행 시 새 오류: `groq.GroqError: The api_key client option must be set ...`
  (`app/services/ai_service.py:11`의 모듈 레벨 `client = Groq(api_key=GROQ_API_KEY)`)
- 원인: 대상 프로젝트가 import 시점에 Groq 클라이언트를 생성하며 키 존재만 검사함. 테스트 실행 환경에 `GROQ_API_KEY` 미설정
- 판단: 커버리지 측정 목적상 실제 키 대신 가짜 키 사용을 권장
  (실제 키는 API 호출 비용·결과 비결정성 문제. 클라이언트 생성 시점에는 키 유효성을 검사하지 않음)

**변경**
- README "문제 해결"에 API 키 오류 대응(가짜 키 환경변수) 추가. 코드 변경 없음

**검증**
- 문서 변경만 있음. 가짜 키로 coverage.json이 생성되는지는 사용자 재실행으로 확인 필요 (**미검증**)
- 대상 프로젝트 테스트가 Groq를 mock하는지, 다른 필수 환경변수가 있는지는 확인하지 못함 (이 환경에 대상 프로젝트 없음)

**다음**
- coverage.json 생성 성공 시 `--dry-run` 실행 → 대상 수·프롬프트 확인
- 참고(대상 프로젝트 개선 제안): import 시점 클라이언트 생성은 테스트 용이성을 떨어뜨림. 지연 생성(lazy init)을 고려할 만함

## 2026-10-10 — 실제 대상 프로젝트 첫 실행 시도: 대상 프로젝트 의존성 누락

**배경**
- 2단계 결과를 실제 프로젝트(`Checkine-Automation-Project/backend`)로 확인하기 위해
  사용자 PC에서 `coverage.json` 생성(pytest --cov --cov-branch)을 시도

**과정**
- `conftest.py` 로딩 중 `ModuleNotFoundError: No module named 'groq'` 발생
  (`app/main.py` → `routers/attendance.py` → `services/attendance_service.py` → `services/ai_service.py`의 `from groq import ...`)
- 원인 분석: 이 도구의 문제가 아니라, pytest를 실행한 Python 환경에 대상 프로젝트 의존성이 설치되지 않은 것.
  coverage.json 생성은 대상 프로젝트의 테스트가 돌아야 가능하므로 대상 프로젝트 환경 준비가 선행 조건

**변경**
- README에 "문제 해결" 섹션 추가: 대상 프로젝트 가상환경 생성·의존성 설치 후 coverage.json 생성 절차 (Windows PowerShell 기준)
- 코드 변경 없음

**검증**
- 문서 변경만 있음. 해결 여부는 사용자 PC에서 의존성 설치 후 재실행으로 확인 필요 (**미검증**)
- 대상 프로젝트의 `requirements.txt`에 `groq`가 포함되어 있는지는 확인하지 못함 (이 환경에 대상 프로젝트 없음)

**다음**
- 의존성 설치 후 coverage.json 생성 → `--dry-run`으로 대상 수·프롬프트 확인

## 2026-10-10 — 구현 2단계: 함수 단위 대상 묶기 + 분기 방향·함수 전체 컨텍스트

**배경**
- 초기 리뷰 지적 1~3번(컨텍스트 부족, 분기 방향 손실, 호출 과다) 해결. 구현 순서 2번. [ADR 0004](decisions/0004-function-level-targets.md) 채택
- 사용자 요구사항 재확인: "모든 작업은 과정까지 히스토리로 남긴다" → `CLAUDE.md` 규칙을
  배경/과정/변경/검증(미검증 포함)/다음 형식으로 구체화

**과정**
- 설계 전에 실제 pytest-cov 7.16.2(`--cov-branch`)로 샘플 프로젝트의 `coverage.json`을 생성해 형식을 확인
  - 발견 1: 한 번도 실행되지 않은 라인에서 나가는 분기도 `missing_branches`에 들어감 (`[25,26]`, `[25,27]`)
    → 라인 갭과 중복이므로 버리기로 함
  - 발견 2: 반복문의 되돌아가는 분기(`[19,18]`), 음수 도착 라인(코드 종료, `[31,-1]`)이 존재 → 설명 문구에 반영
- 첫 구현 dry-run에서 모듈 레벨 갭의 앞뒤 문맥이 바로 위 함수 본문(라인 26-27)까지 섞이는 문제 발견
  → 최상위 함수/클래스 경계에서 문맥을 자르도록 수정
- 구현 중 같은 이름 함수(property getter/setter)가 이름 기준 묶기에서 하나로 합쳐지는 문제를 확인
  → AST 노드 기준으로 묶고 `target_id`에 시작 라인 포함
- 실제 로컬 모델 검증 시도: 개발 환경에서 Ollama 레지스트리·Hugging Face 접근이 차단(프록시 403)되어 모델을 받을 수 없음

**변경**
- `testgen/models.py`: `TestTarget` 신규, `CoverageGap`에 `branch_target`·`describe()` 추가, 스니펫 필드 제거,
  `LLMResponse.gap_id` → `target_id`
- `testgen/coverage_extractor.py`: `extract_gaps` → `extract_targets`. 함수 전체(데코레이터 포함) 소스에
  `>>`(미실행)·`B>`(일부 분기 미실행) 마커, 긴 함수/모듈 레벨은 갭 주변만
- `testgen/prompt_builder.py`: 대상 단위 프롬프트. 미커버 항목 목록(분기 방향 포함)을 명시하고
  "도달 조건을 먼저 파악", "모든 항목을 최소 1개 케이스로" 지시 추가
- `testgen/cli.py`: 대상 단위 실행, `--kind` 필터는 대상 안의 갭을 거른 뒤 빈 대상 제외
- 출력: `gaps.json` → `targets.json`, 파일명 `<target_id>` 기준 (**호환성 깨짐**), `--limit`은 대상 함수 수
- `testgen/config.py`: `SNIPPET_CONTEXT_LINES` 제거, `MAX_FUNCTION_LINES`(120) 등 추가, 미사용 경로 상수 제거

**검증**
- 단위 테스트 21개 통과 (신규 7개: 실제 pytest-cov 출력으로 만든 `tests/fixtures/sample_project` 사용)
- 샘플 프로젝트에서 이전 코드(`3a87c73`)와 비교: 이전 갭 10개(모델당 10회 호출, 분기 방향 없음, 미실행 라인 25의 중복 분기 포함)
  → 현재 갭 9개(분기 방향 포함, 중복 제거)를 대상 3개로 묶어 모델당 3회 호출
- 가짜 OpenAI 호환 서버로 CLI 전체 흐름(`--kind branch` 포함) 확인
- **미검증**: 실제 프로젝트(339개 갭)에서 대상 수가 얼마나 줄어드는지, 실제 로컬 모델의 응답 품질 — 사용자 PC에서 확인 필요

**다음**
- 사용자 PC에서 `--dry-run`으로 실제 프로젝트의 대상 수·프롬프트 확인 → 로컬 모델 `--limit 3` 스모크 테스트
- 구현 3단계: 케이스 → pytest 코드 생성 → 실행 → 커버리지 증가 측정

## 2026-10-10 — 구현 1단계: 로컬 LLM 백엔드 + 출력 스키마 강제/검증

- 배경: 유료 CLI(`claude -p`, `codex exec`) 비용 문제 → 무과금 로컬 모델 지원.
  [ADR 0002](decisions/0002-local-llm-backend.md) 제안 → **채택**
- `testgen/llm_runner.py`: 백엔드 추상화(`CLIBackend`, `OpenAICompatBackend`), `build_backends()`
  - `--models local:<모델명>`으로 Ollama/llama.cpp/LM Studio/vLLM 등 OpenAI 호환 API 호출, `--local-base-url`
- `testgen/case_parser.py` (신규): 출력 JSON 스키마 단일 정의 + 응답 파싱(코드펜스·앞뒤 설명 제거) + 케이스 단위 검증
- 프롬프트 출력 형식을 `{"test_cases": [...]}` 객체로 변경 (이전 배열 형식도 파서가 수용)
- 결과 파일에 `test_cases`/`parse_errors` 추가, 요약에 "파싱 실패"를 호출 실패와 분리 집계
- `tests/` (신규): 파서·백엔드 단위 테스트 14개 (가짜 OpenAI 호환 서버 사용), 표준 라이브러리 unittest
- 검증: 단위 테스트 통과, 가짜 서버로 CLI 전체 흐름 확인.
  실제 로컬 모델 호출은 개발 환경에서 모델 다운로드가 차단되어 **미검증** — 사용자 PC에서 스모크 테스트 필요
- 이후 순서: 2) 함수 단위 갭 묶기 + 분기 방향·함수 전체 컨텍스트 → 3) 테스트 코드 생성·실행·커버리지 측정 → 4) 소형 LLM 인터랙션

## 2026-10-10 — 히스토리 정책 수립, 초기 구조 리뷰

- 개발 과정 전체를 남기기 위한 규칙 도입: `CLAUDE.md`, 본 문서, ADR(`docs/decisions/`), 리뷰(`docs/reviews/`)
  — [ADR 0001](decisions/0001-history-policy.md) 채택
- 1~2단계 코드 리뷰 및 추가 요구사항 검토 — [리뷰](reviews/2026-10-10-initial-review.md)
  - 무과금 로컬 LLM(Ornith 등, Ollama/OpenAI 호환 API) 백엔드 — [ADR 0002](decisions/0002-local-llm-backend.md) 제안
  - 소형 LLM 기반 사용자 인터랙션 계층 — [ADR 0003](decisions/0003-small-llm-interaction.md) 제안
- 코드 변경 없음

## 2026-09-14 — codex 비대화형 커맨드 수정, 진행 상황 정리 (`3a87c73`)

- codex 호출을 `codex -p`(추측)에서 `codex exec -`(공식 문서 확인)로 수정
- 실제 backend `coverage.json`(커버리지 50.25%)으로 1단계 검증: 갭 339개(라인 250 + 브랜치 89)
- `claude` CLI 인증 만료, `codex` 미설치·과금 방식 결정 보류

## 2026-09-14 — 기초 파이프라인 구축 (`6723590`)

- 1단계: pytest-cov `coverage.json` → 미커버 라인/브랜치 갭 추출, AST로 감싸는 함수 매핑
- 2단계: 갭별 ISTQB(경계값 분석·동등분할) 프롬프트 생성, `claude`/`codex` CLI 병렬 호출, 응답 저장
