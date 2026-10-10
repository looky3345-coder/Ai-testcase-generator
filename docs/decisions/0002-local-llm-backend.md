# 0002. 무과금 로컬 LLM 백엔드 도입

- 상태: 채택
- 날짜: 2026-10-10 (제안·채택 동일일, 사용자 승인)

## 배경
`claude -p`, `codex exec`는 구독 또는 API 과금이 필요하다. 비용 없이 파이프라인을 돌릴 수 있어야 한다.

## 검토한 선택지
- A: 로컬 모델만 사용 (Ollama/llama.cpp/LM Studio + Ornith, Qwen 계열 등) — 비용 0, 품질·속도는 하드웨어에 좌우.
- B: 하이브리드 — 기본은 로컬, 선택적으로(`--models claude`) 유료 CLI. 비교·검증용으로 유료를 소량 사용.
- C: 유료 CLI 유지 — 품질 최상, 비용 발생.

## 결정
B. LLM 호출부를 백엔드 인터페이스로 추상화하고, 1순위로 OpenAI 호환 HTTP 백엔드
(Ollama `/v1/chat/completions`, llama.cpp server, LM Studio, vLLM 공통)를 추가한다.
"듀얼 LLM 교차검증"은 서로 다른 로컬 모델 2개(예: Ornith 9B + Qwen 계열)로 대체 가능하다.

## 영향
- 로컬 모델은 맥락 길이·추론력이 작으므로 프롬프트를 함수 단위로 좁히고, JSON 스키마 강제(구조화 출력)를 필수로 한다.
- 품질 판정은 모델 간 일치보다 "실행 + 커버리지 증가"를 기준으로 한다 (리뷰 2026-10-10 참조).

## 구현 메모 (2026-10-10)
- `testgen/llm_runner.py`: `LLMBackend` 인터페이스, `CLIBackend`(기존), `OpenAICompatBackend`(신규, urllib)
- `--models local:<모델명>` 지정. 응답 파일명용 이름은 `local-<모델명>`에서 `:` 등을 `_`로 치환
- 출력 스키마는 `testgen/case_parser.TEST_CASES_SCHEMA`가 단일 기준. 로컬 요청의
  `response_format.json_schema`로 전달하고, 모든 백엔드 응답을 같은 스키마로 검증
- 출력 최상위를 배열 → `{"test_cases": [...]}` 객체로 변경 (OpenAI 호환 json_schema가 객체 루트를 요구하는 경우가 많음).
  이전 형식(최상위 배열) 응답도 파서가 계속 받아준다
