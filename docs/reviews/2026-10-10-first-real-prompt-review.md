# 2026-10-10 실제 프로젝트 첫 프롬프트 검토

대상: `Checkine-Automation-Project/backend`의 `app/services/ai_service.py::analyze_work_hours` 프롬프트
(사용자가 dry-run 결과에서 공유. LLM 호출 전 단계)

## 관찰한 문제

| # | 문제 | 영향 | 조치 |
|---|---|---|---|
| 1 | 한 번도 호출되지 않은 함수가 미커버 항목 6개로 쪼개짐 (107-108, 110-114, 116-117, 119, 121-125, 146-150) | 모델이 "6개 경로를 각각 실행해야 한다"고 오해하고, 항목별 케이스를 억지로 만들 수 있음. 실제로는 "함수를 호출하라"가 핵심 | **수정**: 사이에 실행된 라인이 없는 구간은 합침 + `never_called` 표시와 안내 문구 |
| 2 | 여러 줄 문장의 이어지는 줄(120, 126-145)에 미실행 표시가 없음 | 프롬프트 문자열 본문이 "실행된 코드"처럼 보임 | **수정**: AST 문장 범위로 미실행 표시 확장 |
| 3 | 외부 의존성 정보가 없음 (`Attendance`, `get_kst_now`, `get_today_deep_work_metrics`, `generate_with_retry`) | 모델이 무엇을 mock해야 하는지, 어디서 온 이름인지 모름 → 실행 불가능한 케이스 생성 위험 | **수정**: 함수가 참조하는 모듈 수준 이름과 import 출처 목록 추가 |
| 4 | mock 지시가 없음. `generate_with_retry`(LLM 호출)·현재 시각·Slack 조회 결과가 비결정적 | expected를 구체적으로 쓸 수 없음 | **수정**: "환경 의존 요소는 mock/patch로 고정, preconditions·expected에 구체적으로" 지시 추가 |
| 5 | 프로젝트 컨텍스트가 기본값("pytest 기반 테스트 스위트.") | DB 세션 픽스처, TestClient 등 conftest 정보 없음 | **미조치**: `--framework-hint` 사용 권장. 장기적으로 conftest 픽스처 자동 요약 검토 |
| 6 | patch 경로 모호: 대상 프로젝트가 `from services import ...` 형태(sys.path에 `app/` 추가)로 import | 같은 모듈이 `services.ai_service`/`app.services.ai_service` 두 이름으로 로드될 수 있어 patch 대상이 헷갈림 | **미조치**: 3단계(코드 생성·실행)에서 실제 실행으로 검증하며 결정 |
| 7 | 모델 클래스 필드 정보 없음 (`Attendance.work_seconds`, `status` 등) | 테스트 데이터 준비 방법을 모델이 추측해야 함 | **미조치**: 의존성 목록에 출처는 나오므로 우선 관찰. 필요 시 같은 프로젝트 내 클래스 정의 요약 추가 |

## 양호한 점

- 조건식이 소스에 그대로 보여 경계값 도출이 가능: `len(past_records) < 3` (2/3/4개), `hours <= 5` (17999/18000/18001초)
- 함수 전체가 120줄 이하라 잘림 없이 전달됨

## 재현 및 검증

- 같은 구조(미호출 함수, 여러 줄 dict·f-string, 외부 import, 같은 파일 헬퍼)의 모듈로 실제 pytest-cov 7.16.2 출력을 생성해 재현:
  `missing_lines`에 이어지는 줄·빈 줄이 빠져 구간 5개로 쪼개지는 것 확인 → 수정 후 1개
- `tests/fixtures/sample_project/app/ai_service.py` + 테스트 5개로 고정

## 후속 확인 (개선 후 실제 프로젝트 재실행)

사용자가 최신 코드 + `--framework-hint`로 dry-run을 다시 실행해 같은 함수의 프롬프트를 공유.

- 1~4번 조치가 실제 프로젝트에서도 의도대로 동작: 미커버 항목 6개 → 1개(107-150), 미호출 안내 표시,
  f-string 본문 `>>` 표시, 의존성 5개(import 출처 포함), mock 지시, 프레임워크 힌트 반영
- 5번(프로젝트 컨텍스트)은 `--framework-hint`로 해소
- **6번(patch 경로) 근거 확인**: 의존성 출처가 `from services.slack_service import ...`, `from utils.kst import ...`처럼
  `app.` 접두사 없이 import됨 → 테스트 실행 시 모듈 이름이 `services.ai_service`일 가능성이 높고,
  모델이 `app.services.ai_service.X`로 patch하면 mock이 적용되지 않을 위험. 다음 개선 후보로 승격
- 대상 프로젝트 참고 사항(도구와 무관): 112줄 `diff_minutes` 미사용 변수, 149줄 로그 문구가 실제 사용 중인 Groq가 아닌 `GEMINI ERROR`
