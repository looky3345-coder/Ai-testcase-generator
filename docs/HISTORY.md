# 개발 히스토리

최신 항목이 위. 규칙은 루트 `CLAUDE.md` 참고.

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
