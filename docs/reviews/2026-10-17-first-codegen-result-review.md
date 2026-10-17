# 2026-10-17 첫 실제 코드 생성 결과 검토 (analyze_work_hours, Ornith-1.5-9B)

대상: 사용자 PC 실행 `--qualname analyze_work_hours --generate-code`, 모델 `local-ornith15-9b-16k`
결과: **부분 채택** — 14개 중 통과 2 / 실패로 제거 12, 제거 후 분기 `123→125` 미커버
자료: `output/codegen/a2cd5188eb__local-ornith15-9b-16k/` (보고서 json, `prompt_2.txt`, `code_1.py`)

## 라운드별 결과

| 라운드 | 결과 | 해석 |
|---|---|---|
| 0 | 수집 오류 (`function uses no argument 'records'`) | parametrize 인자를 함수 시그니처에 빠뜨림 |
| 1 | 통과 2 / 실패 12 | 수집 오류는 피드백으로 고침 → 피드백 루프 자체는 작동 |
| 2 | 통과 2 / 실패 12 (동일 목록) | 실패 메시지는 프롬프트에 들어갔으나(`prompt_2.txt` 확인) 모델이 원인을 추론하지 못함 |

## 근본 원인: patch 객체를 만들기만 하고 적용하지 않음

생성 코드의 헬퍼가 `patch.object(...)` 3개를 리스트로 반환만 하고 `start()`/`with` 없이 `stop()`만 호출했다.

| 실패 | 개수 | 직접 원인 |
|---|---|---|
| 결과가 except 경로 문자열 `'AI 매니저가 잠시 디버깅 중...'` | 10 | mock 미적용 → 실제 `generate_with_retry` 호출 → 예외 → fallback |
| `'_patch' object has no attribute 'call_args'` | 2 | call_args를 patch 객체에서 읽음 (mock 객체에 있음) |
| `TypeError: len(None)` (tc14) | 1 | 테스트 전제 오류. SQLAlchemy `Query.all()`은 None을 반환하지 않음 |

(tc3/tc4는 parametrize 2건이라 이름 기준 12개)

## 숨어 있던 문제 (통과/실패 숫자로는 안 보임)

1. **tc7은 우연히 통과**: mock 없이 실제 API 호출이 실패해 fallback이 나와서 통과. API 키가 있는 환경이면 실제 Gemini 호출 → "통과한 테스트는 유지" 규칙이 깨진 테스트를 보존한 사례
2. **TC-1 기대값이 코드와 반대**: 18000초 = 정확히 5.0시간 → `hours <= 5` 참 → 단축 근무 문구 *포함*. 설계는 "미포함"을 기대. mock을 고쳤어도 실패했을 것 (LLM 경계값 해석 오류)
3. **tc12 이름과 내용 불일치**: "모르는 요일 passthrough"라면서 월요일 변환만 검증

## 수동 수정본 (사용자 PC 반영 완료)

`tests/_ai_generated/test_analyze_work_hours_a2cd5188eb.py`를 사람이 고친 버전으로 교체 → **17 passed** (사용자 PC, 대상 프로젝트 venv).
`ExitStack`으로 patch 적용, tc7에 `assert_called_once()`, tc14는 빈 리스트, tc12/12b·tc13b·tc15(정확히 5.0시간) 추가.
함수 원본을 옮긴 스텁에서 변이 5종(`<=`→`<`, 최소 기록 3→4, dnd 반전, 요일 기본값, max_tokens) 모두 검출.

## 도구 조치

| # | 조치 | 상태 |
|---|---|---|
| 1 | 작성 규칙 8 추가: patch는 with/start()로 적용, call_args는 mock 객체에서, mock 호출 여부도 검증 | **수정** |
| 2 | 수정 프롬프트 원인 힌트: `'_patch' object has no attribute` 또는 실제 결과가 소스 except 경로 반환 문자열이면 "mock 미적용 의심" 안내 | **수정** |
| 3 | 통과했지만 patch 대상 mock이 한 번도 호출되지 않은 테스트를 의심 목록으로 (tc7 유형) | **미조치**: 실행 중 mock 호출 추적이 필요해 설계 검토 후 |
| 4 | 경계값 케이스의 assertion 실패를 "기대값 오류 가능성"으로 분류 (TC-1 유형) | **미조치** |
| 5 | 실패 테스트 일괄 제거 대신 원인 분류(테스트 코드 오류 vs 기대값/버그 의심) 후 xfail 보존 | **미조치** |
