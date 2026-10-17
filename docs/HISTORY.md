# 개발 히스토리

최신 항목이 위. 규칙은 루트 `CLAUDE.md` 참고.

## 2026-10-17 — 코드 생성 프롬프트 보강: patch 미적용 실패 대응 (규칙 8 + 원인 힌트)

**배경**
- 사용자 PC 첫 실제 실행(`analyze_work_hours`, Ornith-1.5-9B) 결과 부분 채택: 14개 중 12개 실패로 제거, 라운드 1·2 실패 목록 동일
- 분석 결과는 `docs/reviews/2026-10-17-first-codegen-result-review.md`

**과정**
- 처음엔 "재시도 프롬프트에 실패 이유가 안 들어간다"고 추정했으나 `prompt_2.txt` 확인 결과 실패 메시지는 전달되고 있었음 → 추정 틀림
- 생성 코드를 함수 원본 스텁으로 재실행해 실패 12 / 통과 2를 이름까지 재현. 원인은 하나: patch 객체를 만들기만 하고 적용하지 않음.
  모델은 "결과가 fallback 문자열"이라는 증상만 보고 expected 쪽을 의심해 같은 코드를 반복
- 수동 수정본은 사용자 PC에서 17 passed 확인

**변경**
- `testgen/codegen.py`: `_rules()`에 규칙 8 추가 (첫 생성·수정 프롬프트 공통). `build_fix_prompt()`에 `원인 힌트:` 섹션 —
  실패 메시지에 `'_patch' object has no attribute`가 있거나, 소스의 except 블록이 return하는 문자열(앞 10자)이 실패 메시지에 보이면 mock 미적용을 짚어 줌.
  해당 없으면 프롬프트는 이전과 같음(규칙 8 줄만 추가)
- `tests/test_codegen.py`: `FixPromptHintTest` 5개 (규칙 8 포함, 두 힌트 각각, 일반 실패엔 힌트 없음, 파싱 불가 소스에서도 오류 없음)
- 문서: 리뷰 `docs/reviews/2026-10-17-first-codegen-result-review.md`

**검증**
- 단위 테스트 79개 통과 (신규 5개, 실행 테스트 4개는 pytest-cov 없는 환경이라 기존처럼 건너뜀)
- 힌트 테스트는 실제 실패 메시지 형태(pytest가 줄인 `'AI 매니저가 잠시 디...'`)를 그대로 사용
- **미검증**: 실제 9B 모델이 규칙 8·힌트를 보고 patch를 제대로 쓰는지 — 사용자 PC에서 `--limit 10` 전후 비교 필요.
  변경 전 기준선(같은 대상)을 먼저 남겨야 비교 가능

**다음**
- 사용자 PC에서 변경 전/후 `--limit 10` 비교 (채택·부분 채택·제외, 라운드 0 통과율, 제거 테스트 수)
- 리뷰 문서의 미조치 3~5 (우연한 통과 탐지, 경계값 기대값 오류 분류, 실패 테스트 xfail 보존) 검토

## 2026-10-17 — 3단계 구현: 테스트 코드 생성 → 실행 → 판정 → 피드백 → 실패 테스트 제거

**배경**
- MR #5 병합 확인 후 작업 브랜치를 master로 fast-forward (병합 안 된 커밋 없음, 히스토리 재작성 없음)
- 사용자 결정: 대상 프로젝트 `tests/_ai_generated/`에 생성 테스트 작성 동의, 대상 프로젝트는 GitHub에 있음
  → `looky3345-coder/Checkine-Automation-Project`(공개)를 이 환경에 읽기 전용으로 받아 직접 확인. ADR 0005 채택

**과정**
- 대상 프로젝트 분석: `pytest.ini`의 `pythonpath = . app` 때문에 `ai_service`는 `services.ai_service`로 import됨 → 도구의 모듈명 추정이 맞았음을 확인.
  conftest 픽스처 6개(setup_db, client, user_token, admin_token, user_headers, admin_headers), DB는 `database.SessionLocal`을 SQLite로 교체하는 방식
- 이 환경에 대상 프로젝트 의존성을 설치해 기존 테스트 실행: 49개 통과, coverage.json으로 도구 dry-run → 갭 131/대상 107로 사용자 PC와 동일
- **사람이 직접 4차 케이스를 pytest로 옮겨 기준선 확보**: 10개 통과, `analyze_work_hours` 라인·분기 100% 커버.
  여기서 코드 생성 프롬프트에 필요한 정보를 확인 — import 경로(`from services import ai_service`), DB 세션은 MagicMock 쿼리 체인으로 충분,
  mock 반환형(`get_kst_now`는 datetime이어야 함 — 4차 케이스의 'Monday'는 실제로 AttributeError)
- 구현 중 발견: pytest JUnit은 수집 오류를 빈 classname + `tests._ai_generated.test_…` 이름으로 기록 → 이름 접두사가 아니라 classname으로 판별하도록 수정(커밋 전)
- **실제 대상 프로젝트로 종단 확인**(LLM은 가짜 서버로 대체): 사용자의 4차 케이스 → 1차 코드(실제 모델이 저지른 'Monday' 실수 재현) 실행 시
  통과 1 / 실패 1 / 미실행 라인 14·분기 2 → 실패 메시지 `AttributeError: 'str' object has no attribute 'strftime'`와 미실행 라인이 수정 프롬프트에 전달됨 →
  2차 코드 통과 10 / 함수 완전 커버 → **채택**. 대상 프로젝트에 `.coverage` 등 부산물이 남지 않음을 확인 (검증 후 생성 파일은 로컬 클론에서 삭제, 대상 저장소에는 push하지 않음)

**변경**
- `testgen/codegen.py` (신규): 프로젝트 테스트 환경 수집, 코드 생성/수정 프롬프트, 코드 추출·문법 검사, 실행·JUnit/커버리지 판정, 실패 테스트 제거, 전체 루프
- `testgen/cli.py`: `--generate-code`, `--target-python`(기본 `.venv` 자동 탐색), `--fix-rounds`(2), `--test-timeout`(300), `--generated-dir`, 3단계 요약
- `testgen/llm_runner.py`: `run(..., structured=False)` — 코드 생성은 JSON 스키마 강제 없이
- `testgen/models.py`, `coverage_extractor.py`: `TestTarget.end_line` (함수 범위 판정용)
- 문서: README 전체 구조(3~5단계 통합)·3단계 사용법, ADR 0005 채택·구현 메모, 설치 가이드 4-4

**검증**
- 단위 테스트 74개 통과 (신규 11개). 그중 실제 pytest 실행 테스트 4개(피드백으로 실패 수정→채택, 지속 실패 테스트 제거→부분 채택,
  import 오류→제외·파일 삭제, 문법 오류 재시도)는 pytest-cov가 있는 Python에서 실행 (`TESTGEN_TEST_PYTHON`), 기본 환경에서는 건너뜀
- 실제 대상 프로젝트 + 대상 프로젝트 venv로 종단 실행 확인 (위 과정)
- **미검증**: 실제 Ornith-1.5-9B가 쓴 코드의 품질과 수정 라운드 효과, Windows 경로에서의 실행 — 사용자 PC 실행 필요

**다음**
- 사용자 PC에서 `--qualname analyze_work_hours --generate-code` 실행 → 라운드별 결과 검토
- 결과에 따라 코드 생성 프롬프트 보강, 이후 `--limit` + `--resume`으로 범위 확대

## 2026-10-10 — 오늘 작업 마무리: master 병합 예정, 다음 세션 시작점

**배경**
- 사용자 결정: 현재 내용으로 master에 병합(MR)하고, 나머지는 다음 날 이어서 진행

**오늘 도달한 상태**
- 1단계(갭 추출·함수 단위 묶기·분기 체크리스트)와 2단계(ISTQB 케이스 설계, 로컬 LLM) 동작.
  실제 프로젝트: 갭 131개 → 대상 함수 107개. `analyze_work_hours`로 4회 반복 개선해 경계값·오라클·정상/예외 경로까지 설계 가능
- 집 데스크톱: Ollama + Ornith-1.5-9B(`ornith15-9b-16k`, num_ctx 16384), 함수 1개당 약 23~57초
- 단위 테스트 63개 통과

**다음 세션 시작점**
1. 사용자 결정 2건 (ADR 0005)
   - 대상 프로젝트 `tests/_ai_generated/`에 생성 테스트를 쓰는 것에 대한 동의
   - 대상 프로젝트 `tests/conftest.py`의 픽스처 정보 공유
2. 결정 후 ADR 0005 채택 → 3단계(pytest 코드 생성 → 실행 → 커버리지 측정 → 피드백) 구현, `--qualname analyze_work_hours`로 검증
3. 보류 중인 개선 후보: 실행 전 모델 컨텍스트 한도 점검/경고, 응답 파일명 가독성(함수명 포함)

**변경**
- 문서만(본 항목)

**과정**
- MR 준비 중 확인: 이 브랜치는 이미 master에 3회 병합됨(PR #1~#3). master에만 있는 병합 커밋 때문에 master가 브랜치의 조상이 아니었음
  → `CLAUDE.md` 규칙(공유 브랜치 rebase 금지)에 따라 master를 브랜치로 **병합 커밋**으로 가져옴. 내용 변경 없음
  (master 대비 차이: 마지막 병합 이후 커밋 15개, 17개 파일)

**검증**
- 마무리 시점 단위 테스트 63개 통과(master 병합 후 재확인), master가 브랜치의 조상이 됨을 확인
- 사용자 요청으로 MR 생성: looky3345-coder/Ai-testcase-generator#5 (`claude/llm-test-case-generator-lgihpf` → `master`)

## 2026-10-10 — 4차 결과: 경계값 해결, 남은 문제는 실행 검증 영역 → 3단계 설계 제안(ADR 0005)

**배경**
- 경계값 입력 환산·공통 사전조건 반영 후 재실행: 22.9초, 4,304 토큰, 케이스 8개
- 사용자 질문: "pytest 코드 생성은 어디에 되었나?" → **아직 미구현**(3단계)임을 안내. 지금까지 결과물은 케이스 설계서

**과정**
- 개선 확인: 경계값 17999/18000/18001초 사용(3회 연속 실패 후 해결), common_preconditions 사용
- 남은 문제 H~L 분석 ([리뷰 4차 결과](reviews/2026-10-10-first-llm-cases-review.md)): mock 반환형 오류('Monday' 문자열에 `.strftime`),
  필수 mock 누락 재발, 불필요 mock, falsy 분기 누락 — 모두 실행하면 즉시 드러나는 종류
- 판단: 프롬프트 규칙을 계속 늘리는 것은 수확 체감. 실제 실행·커버리지 측정으로 판정·피드백하는 3단계로 이행 제안
- 설계 쟁점 정리: 생성 테스트가 대상 프로젝트의 conftest 픽스처를 쓰려면 **대상 프로젝트 tests 아래에 파일을 써야 함** → 사용자 동의 필요

**변경**
- `docs/decisions/0005-test-code-generation-and-execution.md` (상태: 제안)
- 리뷰 문서에 4차 결과. 코드 변경 없음

**검증**
- 문서만

**다음**
- 사용자 결정 대기: 대상 프로젝트 `tests/_ai_generated/`에 생성 테스트를 쓰는 것에 대한 동의, `tests/conftest.py` 내용(픽스처 이름) 공유
- 결정 후 ADR 0005 채택 → `--qualname analyze_work_hours` 1개로 3단계 구현·검증

## 2026-10-10 — 3차 결과: 오라클 해결 → 경계값 입력 환산 자동 계산, 공통 사전조건 분리

**배경**
- 규칙 보강 후 재실행: 25.1초, 케이스 8개, 4,456 토큰. 오라클(mock 호출 인자 검증)·정상 완료 경로·기법 라벨 개선 확인
  ([리뷰 3차 결과](reviews/2026-10-10-first-llm-cases-review.md))

**과정**
- 남은 문제: `hours <= 5` 경계값을 3회 연속 잘못 고름(10000초) → 소형 모델은 단위 환산을 못 한다고 판단, 도구가 계산하기로 함.
  `변수 = 이름 / 상수`, `이름 * 상수`, `상수 * 이름` 형태의 대입만 다루는 단순 규칙 (여러 단계 환산은 미지원)
- **도구 측 원인 발견**: TC-4~7에 `generate_with_retry` mock이 빠져 실제 API를 호출하게 됨. 2차에서 추가한 규칙 9
  ("사전조건을 반복하지 말고 차이만")를 모델이 공통 mock 생략으로 해석한 것 → 짧게 쓰라는 요구와 빠짐없이 쓰라는 요구를
  출력 구조로 분리(`common_preconditions`)
- 테스트 작성 중 기대값을 잘못 쓴 테스트 1건(정수 환산 결과 표기) → 코드가 아니라 테스트를 수정
- F(falsy 쪽 일부 누락)·G(반환값/인자 혼동)는 지시로 해결하기보다 3단계 실행 검증으로 잡는 것이 맞다고 판단

**변경**
- `testgen/coverage_extractor.py`: `_linear_conversions()`, 경계값 힌트에 입력 단위 환산(정수면 경계-1/경계/경계+1, 아니면 경계값)
- `testgen/case_parser.py`: 스키마에 `common_preconditions`(필수), 이전 형식 허용, 잘린 응답에서도 회수
- `testgen/models.py`, `cli.py`: 응답에 `common_preconditions` 저장
- `testgen/report.py`: CSV에 `common_preconditions` 열
- `testgen/prompt_builder.py`: 출력 예시에 공통 사전조건, 규칙 9 재작성
- 출력 형식 변경(최상위에 `common_preconditions` 추가) — 이전 응답 파일·형식도 계속 읽음

**검증**
- 단위 테스트 63개 통과 (신규 5개: 공통 사전조건 파싱·잘린 응답 회수, 곱셈·상수 선행·비정수 환산, 관련 없는 비교 미변경. 기존 2개 보강)
- 실제 함수 발췌에서 "`current_work_seconds` = 17999 / 18000 / 18001" 제시 확인
- **미검증**: 모델이 환산된 경계값과 공통 사전조건을 실제로 반영하는지 — 사용자 재실행 필요

**다음**
- 재실행으로 확인 후 3단계(케이스 → pytest 코드 생성 → 실행 → 커버리지 측정) 설계 착수 제안

## 2026-10-10 — 나눠 실행하기(`--resume`): 이미 성공한 대상은 재사용

**배경**
- 전체 107개 실행 시간 추정(1~2시간)에 대해 사용자가 GPU 부담을 우려

**과정**
- 하드웨어 측면: 1~2시간 연속 추론은 같은 시간의 게임과 같은 수준으로 판단 (설치 가이드 "GPU 부담" 근거 재안내, 전력 제한 옵션 안내)
- 실질적인 부담은 "한 번에 오래 걸리는 것"과 "다시 실행하면 처음부터 전부 다시 하는 구조"라고 판단 → 나눠 실행 + 재사용 기능을 추가
- 재사용 조건 설계: 같은 대상×모델이고 **같은 프롬프트**(해시 비교)로 케이스를 얻은 경우만. 실패·파싱 실패·프롬프트 변경(도구 업데이트,
  힌트 변경)은 다시 호출 — 개선 전 프롬프트의 낡은 결과가 섞이지 않도록
- 1~2시간 추정은 가장 복잡한 함수(분기 8개, 57초) 기준이라 과대 추정일 가능성을 함께 안내. 실제 평균은 나눠 실행하며 측정 예정

**변경**
- `testgen/cli.py`: `--resume` (이전 응답 파일의 `prompt_sha` 비교 후 재사용), 재사용 건수 표시
- `testgen/models.py`: `LLMResponse.prompt_sha`(파일에 저장), `reused`(표시용, 파일 미저장), `from_dict()`
- 문서: README 옵션, 설치 가이드 "4-3. 전체 실행을 나눠서 하기"

**검증**
- 단위 테스트 58개 통과 (신규 2개: `--limit 2` 후 `--resume`으로 나머지 4개만 호출·CSV에 6개 포함, 힌트 변경 시 재호출,
  `--resume` 없으면 재호출)
- **미검증**: 사용자 PC에서 실제 나눠 실행

**다음**
- 개선 규칙으로 `analyze_work_hours` 재실행 결과 확인 → 3단계(코드 생성·실행·커버리지 측정) 착수 여부 결정

## 2026-10-10 — 16K 컨텍스트로 케이스 12개 생성 → 2차 품질 검토 → 오라클·try·경계값·중복 규칙 보강

**배경**
- `ornith15-9b-16k` 별칭으로 재실행: **잘림 해소**, 케이스 12개, 57.4초, 5,716 토큰, `finish_reason=stop`
  (직전 항목의 미검증 "16K 별칭으로 잘림 해소" 확인. GPU 적재 여부는 미보고)

**과정**
- 1차 문제 6개와 비교 ([리뷰 2차 결과](reviews/2026-10-10-first-llm-cases-review.md)): 3개 해결(mock 경로, 케이스 수, 동등분할 대부분),
  2개 부분 개선(기법 라벨, `hours <= 5` 경계값), 1개 과교정(예외 경로를 모든 케이스에 적용)
- 새로 드러난 핵심 문제: **테스트 오라클** — 분기 효과가 반환값이 아니라 mock에 넘기는 prompt 문자열에만 드러나는데
  expected가 모두 같은 fallback 문자열 → 이대로 테스트를 만들면 분기 로직이 틀려도 통과
- 규칙 문구에 실제 대상 코드의 값을 그대로 쓰면 모델이 답을 베낄 수 있어, 예시는 다른 값(`minutes`, 599/600/601초)으로 일반화
- 콘솔 상태의 "버림 N건"이 파싱 메시지 전체 개수를 세고 있어, 중복 경고·회수 안내까지 "버림"으로 보일 문제를 발견 → 종류별로 분리

**변경**
- `testgen/prompt_builder.py`: 규칙 7(경계값 N-1·N, 단위 환산), 8(정상 완료 최소 1개, 예외는 except 겨냥에만), 10(mock 호출 인자 검증), 11(중복 금지)
- `testgen/case_parser.py`: `_duplicate_warnings()` — 입력·사전조건이 같은 케이스를 "중복 의심"으로 표시 (버리지 않음)
- `testgen/cli.py`: 상태 표시를 "버림 / 중복 의심 / 잘린 응답에서 회수"로 분리
- `testgen/report.py`: CSV에 `review_note` 열 (케이스별 중복 의심 표시)

**검증**
- 단위 테스트 56개 통과 (신규 1개 + 기존 2개 보강: 중복 표시, CSV review_note, 콘솔 "중복 의심 1건", 프롬프트 규칙 문구)
- **미검증**: 보강된 규칙으로 모델이 오라클(호출 인자 검증)·정상 완료 케이스·실제 경계값을 쓰는지 — 사용자 재실행 필요

**다음**
- 같은 명령으로 재실행 → 2차 문제(A·B·C, 라벨·경계값) 비교
- 이후 단계 제안: 3단계(케이스 → pytest 코드 생성 → 실행 → 커버리지 증가 측정). 오라클·경계값의 실제 효과는 실행으로만 확정 가능

## 2026-10-10 — 응답 잘림 원인 확정: Ollama 기본 컨텍스트 4096

**배경**
- 직전 항목에서 미검증으로 남긴 잘림 원인을 사용자가 응답 JSON의 usage로 확인해 공유

**과정**
- usage: `prompt_tokens 2440 + completion_tokens 1656 = total_tokens 4096` → Ollama 기본 컨텍스트 4096에 정확히 도달. **추정 확정**
- 설치 가이드의 `OLLAMA_CONTEXT_LENGTH=8192` 설정이 실제로는 적용되지 않은 상태였음 (미설정 또는 재시작 누락).
  → 환경변수 대신 Modelfile `num_ctx`로 모델 별칭에 고정하는 방법(직전 항목에서 가이드에 추가)을 사용하도록 안내
- 출력 여유 계산: 체크리스트 반영 프롬프트는 입력 약 2,440 토큰 → 4096이면 출력 약 1,650 토큰뿐.
  체크리스트 8개 항목 양쪽 커버(케이스 10개 안팎)에는 부족. 16384면 출력 13,000+ 토큰 여유

**변경**
- 문서만(본 항목). 코드 변경 없음

**검증**
- usage 수치로 원인 확정 (사용자 PC 실측)
- **미검증**: `ornith15-9b-16k` 별칭으로 잘림이 해소되는지, 16K에서 100% GPU 유지 여부

**다음**
- 16K 별칭으로 재실행 → 케이스 품질을 리뷰 문서의 문제 6개와 비교
- 검토 후보: 실행 전에 모델의 컨텍스트 한도를 확인해 프롬프트가 한도에 비해 크면 경고 (같은 실수 재발 방지)

## 2026-10-10 — 체크리스트 도입 후 재실행: 응답 잘림(finish_reason=length) → 완성 케이스 회수, 토큰 표시

**배경**
- 체크리스트 프롬프트로 재실행: `PARSE FAIL (최상위에 'test_cases' 배열이 없습니다) [finish_reason=length]` (56.1초)
- 사용자 질문: history를 계속 남기고 있는지 → 23개 항목·ADR 4건·리뷰 3건, 22개 커밋이 HISTORY를 함께 수정했음을 확인해 답변

**과정**
- 체크리스트 효과로 모델이 케이스를 많이 쓰기 시작(56초, 직전 9.4초) → 출력 도중 한도에 걸려 잘림
- 오류 메시지가 이상한 이유 분석: 바깥 JSON이 닫히지 않아 파서가 **첫 케이스 객체를 최상위로 오인** →
  "test_cases 배열 없음"으로 판단하고 완성된 케이스까지 전부 버림
- 한도 원인 추정: 직전 성공은 입력 1,843 + 출력 527 = 2,370 토큰. 이번에 합계가 Ollama 기본 컨텍스트 4096에 닿았을 가능성이 높음
  (가이드의 `OLLAMA_CONTEXT_LENGTH` 미적용 또는 재시작 누락 추정). 응답 JSON의 `usage`로 확정 필요 → 사용자에게 요청
- 환경변수 방식은 적용 여부가 안 보이므로, Modelfile `PARAMETER num_ctx`로 모델 별칭에 한도를 고정하는 방법을 가이드에 추가

**변경**
- `testgen/case_parser.py`: `_salvage_truncated()` — 닫히지 않은 응답에서 완성된 케이스만 회수, "완성된 케이스 N개만 회수" 표시
- `testgen/llm_runner.py`, `models.py`: 응답 `usage`의 입력/출력 토큰 수 보관
- `testgen/cli.py`: 잘림 표시에 "입력 + 출력 = 합계 토큰" 추가
- `testgen/prompt_builder.py`: 규칙 9 — 각 필드 간결하게, 사전조건 반복 금지
- `docs/local-llm-setup.md`: "컨텍스트 한도 늘리기"(Modelfile num_ctx 16384 별칭), 문제 해결표 갱신

**검증**
- 단위 테스트 55개 통과 (신규 2개: 잘린 응답에서 완성 케이스 2개 회수(문자열 안 중괄호 포함), 완성 케이스 없는 잘림. CLI 토큰 표시 검증 보강)
- **미검증**: 실제 잘림 원인(컨텍스트 4096 여부) — 응답 JSON의 usage 확인 대기. num_ctx 16384 별칭의 VRAM 적재 여부

**다음**
- usage 확인 → 컨텍스트 한도 늘린 별칭으로 재실행 → 리뷰 문서의 문제 6개와 비교

## 2026-10-10 — 첫 테스트 케이스 생성 성공 → 품질 검토 → 분기 체크리스트 도입

**배경**
- thinking off 후 재실행: **첫 성공**. 9.4초(46초 → 9.4초), 입력 1,843/출력 527 토큰, `finish_reason=stop`, 케이스 2개
- `reasoning_effort: "none"`으로 Ornith-1.5-9B의 thinking이 꺼지는 것 확인 (직전 항목의 미검증 해소).
  thinking off에서도 JSON 스키마를 지킴 (Qwen3.5 format 무시 이슈는 이 실행에서는 나타나지 않음)
- 같은 날 확인: push 여부 질문 → 원격 브랜치 최신 커밋 일치 확인, PC에서 브랜치 확인 방법 안내

**과정**
- QA 관점 검토 → 문제 6개 ([리뷰](reviews/2026-10-10-first-llm-cases-review.md)): 기법 라벨 오류, `hours <= 5` 참 경로 누락,
  except 경로 착시(mock 반환값 = fallback 문구), 동등분할 누락, `Session` patch, 케이스 2개뿐
- 원인 판단: 소형 모델이 추상 지시를 구체화하지 못함 → 분기 지점·경계 후보를 AST로 추출해 체크리스트로 제공
- 사용자가 공유한 프롬프트의 함수 원문을 테스트 픽스처로 보존해 실제 코드 기준으로 추출 결과 검증 (8개 항목)
- 구현 중 기존 버그 발견: 본문 첫 문장이 데코레이터 달린 내부 함수면 그 데코레이터가 시그니처에 섞임(`def logged(fn): @wraps(fn)`) → 수정

**변경**
- `testgen/coverage_extractor.py`: `_decision_points()`, `_boundary_hints()`, 타입 표기 전용 의존성 표시, 시그니처 버그 수정
- `testgen/models.py`: `TestTarget.decision_points` (targets.json에도 출력)
- `testgen/prompt_builder.py`: "분기·조건 체크리스트" 섹션, 규칙 6~8(전 항목 양쪽 커버, technique 표기 기준, 예외는 side_effect), patch 전체 경로 기재
- `tests/fixtures/real_excerpts/analyze_work_hours.py`(실제 함수 발췌), 테스트 4개 추가

**검증**
- 단위 테스트 53개 통과
- 실제 함수 발췌에서 체크리스트 8개(경계 3·5, `or` 기본값 3개, 삼항 2개, try) 추출 확인
- **미검증**: 개선 프롬프트로 모델이 실제로 더 나은 케이스를 내는지 — 사용자 재실행 필요

**다음**
- 같은 명령으로 재실행 → 리뷰 문서의 문제 6개와 비교
- 품질이 충분하면 `--qualname` 없이 소규모(`--limit 5`) → 전체 107개

## 2026-10-10 — 두 번째 실호출: 답 본문이 빈 응답(추론형 모델 thinking) → thinking 기본 끄기

**배경**
- 별칭 문제 해결 후 재실행: `PARSE FAIL (응답에서 JSON을 찾을 수 없습니다)` (46.0초)
- 사용자가 공유한 응답 파일: `"raw_output": ""` — 모델은 46초 동안 생성했지만 답(content)이 비어 있음

**과정**
- 가설 3개(① `<think>` 블록에 섞인 중괄호 ② 출력 잘림 ③ 본문 비어 있음)를 세우고, 응답 파일을 받기 전에
  ①②③이 모두 드러나도록 진단 기능부터 보강 (`<think>` 제거, `finish_reason` 기록, 원본 HTTP 응답 보관)
- 응답 파일로 ③ 확정. 조사 결과: Ollama에서 추론형 모델은 사고 과정을 별도 `reasoning` 필드로 내보내고 `content`가 비는 사례가
  보고되어 있고, OpenAI 호환 API에 `reasoning_effort: "none"`을 보내면 thinking이 꺼진다는 보고가 있음
- 주의 사항(조사): Qwen3.5 계열은 thinking을 끄면 Ollama의 `format`(JSON 강제)이 무시된다는 Ollama 이슈(#14645)가 있음.
  Ornith-1.5는 Qwen3.5 기반이라 해당될 수 있음 → 형식 강제가 안 돼도 응답 후 파싱·스키마 검증이 있으므로 우선 진행
- 테스트 작성 중 **직전 진단 보강 코드의 버그 발견**: `finish_reason=length` 표시를 if/elif/else 사슬 가운데 끼워 넣어
  파싱 실패가 "OK, 케이스 0개"로도 표시되고 성공·실패에 이중 집계됨. 커밋 전이라 사용자에게 배포되지는 않음 → 수정 + 회귀 테스트

**변경**
- `testgen/llm_runner.py`: `thinking` 옵션(기본 False → `reasoning_effort: "none"` 전송), 응답의 `reasoning`/`finish_reason`/원본 본문 보관
- `testgen/case_parser.py`: `<think>…</think>` 제거, 빈 본문·닫히지 않은 `<think>`(잘림)를 구분한 오류 메시지
- `testgen/models.py`: `LLMResponse.finish_reason`, `raw_response`, `reasoning`
- `testgen/cli.py`: `--local-thinking off|on`(기본 off), "본문은 비고 reasoning만 있음" 안내, 잘림 표시(상태 분류 버그 수정 포함)
- 문서: README 옵션, 설치 가이드 문제 해결표 3행

**검증**
- 단위 테스트 49개 통과 (신규 8개: think 제거/잘림/빈 본문, thinking 끄기 요청값, reasoning 보관, 실제 사례 재현(content 빈 응답),
  잘림 표시와 이중 집계 회귀)
- **미검증**: Ornith-1.5-9B가 `reasoning_effort: "none"`으로 실제 thinking을 끄는지, 끈 상태에서 JSON을 지키는지 — 사용자 재실행 필요

**다음**
- 재실행 결과에 따라: 성공 → 케이스 품질 검토 / 형식 이탈 → Ollama 네이티브 API(`think`, `format`, `num_ctx`) 백엔드 검토

## 2026-10-10 — 첫 실호출: Ollama 연결 성공, 모델 이름 불일치(404) → 호출 전 모델 확인 추가

**배경**
- 집 데스크톱에서 첫 실호출 (`--qualname analyze_work_hours --models local:ornith15-9b --workers 1`)
- 결과: `FAIL (HTTP 404: model 'ornith15-9b' not found)` (2.1초)

**과정**
- 의미 있는 진전: 404는 Ollama가 돌려준 응답이므로 **OpenAICompatBackend → 실제 Ollama 연결은 처음으로 실사용 확인**됨
- 원인: 가이드의 `ollama cp ... ornith15-9b` 별칭 단계를 건너뛰었거나 다른 이름으로 받아짐 (사용자 `ollama list` 확인 대기)
- 문제점: 이름이 틀려도 대상마다 호출을 시도한 뒤에야 실패를 알 수 있음. 107개 전체 실행이면 107건 모두 404
- 조치: 호출 전에 OpenAI 호환 `GET /models`로 모델 존재를 확인하고, 없으면 사용 가능한 이름 목록과 함께 즉시 종료.
  Ollama는 태그 없는 이름을 `:latest`로 취급하므로 비교 시 반영. `/models`를 지원하지 않는 런타임은 점검을 건너뜀

**변경**
- `testgen/llm_runner.py`: `LLMBackend.check_model()`(기본 None), `OpenAICompatBackend.check_model()`, 헤더 생성 `_headers()`로 정리
- `testgen/cli.py`: 백엔드 생성 직후 전체 백엔드 사전 점검, 실패 시 종료 코드 1
- 테스트: 가짜 서버에 `/v1/models` 응답 추가. 일치(`:latest` 포함)/불일치 목록 표시/미지원 건너뜀/연결 실패,
  CLI에서 잘못된 모델이면 chat 호출 0건으로 종료하는지 검증 (신규 5개)

**검증**
- 단위 테스트 41개 통과
- **미검증**: 실제 Ollama의 `/v1/models` 응답 형식(`data[].id`)은 OpenAI 호환 규격 기준으로 구현했으며 사용자 PC에서 미확인

**다음**
- 사용자: `ollama list`로 이름 확인 → 별칭 생성 또는 전체 이름 사용 → 재실행

## 2026-10-10 — 집 데스크톱 dry-run 성공 + 경로 끝 역슬래시 오류 감지

**배경**
- 집 데스크톱에서 dry-run 실행 시 `error: the following arguments are required: --source-root` 발생.
  사용자는 `--source-root`를 분명히 입력한 상태

**과정**
- 원인: 경로를 `"...\backend\"`처럼 끝에 `\`를 붙여 따옴표로 감쌈. Windows의 명령줄 분해 규칙상 `\"`는 따옴표 문자로 해석되어
  따옴표가 닫히지 않고, 뒤의 `--source-root ...`까지 `--coverage-json`의 값 하나로 합쳐짐
- argparse 오류 메시지만으로는 원인을 알 수 없으므로, 인자 값 안에 `"`가 남아 있으면 이 실수로 보고 안내를 먼저 출력하도록 함
- 구현 직후 확인에서 안내는 stderr의 맨 앞에 출력되고(이후 argparse usage/오류) `tail`로 보면 안 보였음 → `head`로 확인
- 사용자가 `\`를 지우고 재실행 → **성공**

**변경**
- `testgen/cli.py`: `warn_swallowed_quote()` — 인자 값에 `"`가 있으면 원인과 수정 예시를 출력 (파싱 자체는 그대로)
- `tests/test_cli.py`: 깨진 인자 재현 시 안내 출력·정상 인자에는 미출력 테스트 2개
- `README.md` "문제 해결"에 해당 오류 항목 추가

**검증**
- 단위 테스트 36개 통과 (신규 2개)
- **집 데스크톱 실제 결과**: `--coverage-json`에 폴더 지정 → 내부 coverage.json 자동 사용 확인
  (직전 "폴더 처리 개선"의 미검증 항목 해소). 갭 131개 → 대상 107개로 회사 PC와 동일, `--qualname analyze_work_hours`로 1개 선택 확인
- 따옴표 안내 문구 자체는 사용자 PC에서 아직 보지 않음 (이 기능 추가 전에 사용자가 직접 고침)

**다음**
- `output/prompts/` 의 patch 경로 문구 확인 → 첫 실호출 (`--models local:ornith15-9b --workers 1`)

## 2026-10-10 — README에 가상환경 활성화 실패 대응 추가

**배경**
- 집 데스크톱에서 `Activate.ps1` 실행이 안 될 때의 대응을 다시 질문 (회사 PC에서도 같은 질문이 있었음)

**과정**
- 같은 질문이 반복됨 → 채팅 안내만으로는 부족하다고 판단해 README "문제 해결"에 고정
- 원인 3가지(실행 정책, `.venv` 없음/위치 오류, cmd 창)와 활성화 없이 `.venv\Scripts\python.exe`를 직접 쓰는 우회법 정리

**변경**
- `README.md` "문제 해결"에 오류 메시지별 조치표 추가. 코드 변경 없음

**검증**
- 문서만. 집 데스크톱에서 어떤 오류였는지는 사용자 회신 대기 (**미확인**)

**다음**
- 가상환경 준비 → coverage.json 생성 → dry-run → 첫 실호출

## 2026-10-10 — 설치 가이드에 새 PC용 coverage.json 생성 단계 추가

**배경**
- 사용자 질문: 집 데스크톱에서 coverage.json 생성을 다시 해야 하는가

**과정**
- coverage.json은 테스트 실행 산출물이라 보통 git에 포함되지 않음 → 새 PC에서 clone했다면 없음.
  복사해 왔더라도 코드가 바뀌었으면 라인 번호가 어긋나므로 재생성이 안전하다고 판단
- 설치 가이드(`docs/local-llm-setup.md`)의 "첫 실호출"에 이 단계가 빠져 있었음을 발견

**변경**
- 가이드 4장을 4-1(coverage.json 생성: .venv, 의존성, 가짜 GROQ_API_KEY 포함) / 4-2(테스트 케이스 생성)로 분리. 코드 변경 없음

**검증**
- 문서만. 집 데스크톱에서의 생성 성공 여부는 사용자 확인 대기 (**미검증**)

**다음**
- coverage.json 생성 → dry-run → 첫 실호출

## 2026-10-10 — 집 데스크톱 환경 세팅 완료 (사용자 보고)

**배경**
- 사용자 보고: 집 데스크톱(RAM 32GB, RX 7800 XT)에 Ollama 설치 및 프로젝트 세팅 완료

**과정**
- 첫 실호출 전 확인 순서를 안내: `ollama list`/`run`/`ps`로 모델·GPU 확인 → `--qualname analyze_work_hours --dry-run`으로
  대상 1개·patch 경로 문구 확인 → `--models local:ornith15-9b --workers 1`로 실호출
- 공유 요청 항목: 콘솔 출력(상태·소요 시간), `test_cases.csv`, 실패 시 응답 JSON

**변경**
- 문서만(본 항목). 코드 변경 없음

**검증**
- 세팅 상태는 사용자 보고 기준. 모델 이름, GPU 사용 여부, 컨텍스트 길이 설정 적용 여부는 아직 미확인 (**미검증**)

**다음**
- 첫 실호출 결과 분석 → 프롬프트/파서 조정 → 3단계(테스트 코드 생성·실행·커버리지 측정) 설계

## 2026-10-10 — Ornith-1.5-9B 받는 방법 확정

**배경**
- 사용자: Ollama는 이미 설치되어 있음. 모델 목록에서 Ornith 1.5를 어디서 찾는지 질문

**과정**
- `ollama list`는 로컬에 받은 모델만 보여준다는 점을 안내
- 검색 결과: Ollama 공식 라이브러리 등록 여부는 확인 불가(튜토리얼의 `ornith-1.5-9b` 이름은 미검증).
  Hugging Face에 커뮤니티 GGUF 다수 존재 → `bartowski/Ornith-1.5-9B-GGUF`의 Q4_K_M(5.91GB)을 `hf.co/` 경로로 받는 방식으로 결정
- 도구 호환성 확인: `--models local:<이름>`은 `local:` 뒤를 그대로 모델명으로 쓰므로 `hf.co/...:Q4_K_M` 같은 긴 이름도 동작
  (응답 파일명에서는 `/`, `:`가 `_`로 치환됨). 편의를 위해 `ollama cp`로 `ornith15-9b` 별칭을 붙이도록 안내

**변경**
- `docs/local-llm-setup.md`: 모델 받기 절차를 구체 명령으로 교체, 이후 예시의 모델명을 `ornith15-9b`로 통일. 코드 변경 없음

**검증**
- 문서만. `hf.co` pull 성공 여부·실제 크기는 집 데스크톱에서 확인 (**미검증**)

**다음**
- 집 데스크톱: pull → `ollama ps`로 GPU 확인 → 첫 실호출

## 2026-10-10 — 로컬 LLM 사용 시 GPU 부담 안내

**배경**
- 사용자 질문: Ornith-1.5-9B를 돌리면 GPU(RX 7800 XT)에 부담이 되지 않는가

**과정**
- 이 도구의 사용 패턴을 기준으로 판단: 호출당 수 초~수십 초의 간헐적 부하, 첫 실행 1건, 전체 107건도 게임 한두 판 수준 시간(실측 전 추정)
- 부하 강도는 게임과 유사, 9B 모델은 VRAM 절반 이하 사용 → 하드웨어 위험은 사실상 없다고 판단.
  실사용상 주의점은 사용 후 VRAM 점유(keep_alive)와 35B 사용 시 CPU 부하

**변경**
- `docs/local-llm-setup.md`에 "GPU 부담" 섹션 추가 (온도 확인 방법, `ollama stop`, 전력 제한 옵션). 코드 변경 없음

**검증**
- 문서만. 실제 온도·소요 시간은 집 데스크톱 첫 실행에서 확인 (**미검증**)

**다음**
- 첫 실행 시 소요 시간과 GPU 온도를 함께 기록하면 전체 실행 시간 추정에 활용

## 2026-10-10 — 1순위 로컬 모델을 Ornith-1.5-9B로 변경

**배경**
- 사용자가 외부에서 "1.5 9B 모델" 추천을 받았다고 공유 ("OLLAM 1.5 9B"로 표기 → Ornith-1.5-9B로 해석, 사용자 확인 대기)

**과정**
- 확인: Ornith-1.5는 2026-08 공개된 후속 버전. 9B는 9.4B dense, 컨텍스트 262K, MIT, Hugging Face 공개.
  제조사 발표 벤치마크는 1.0-9B보다 높으나 독립 검증 없음
- 크기가 1.0-9B와 같아 직전 항목의 하드웨어 판단(VRAM 16GB에 전부 적재)은 그대로 유효
- 문서 수정 스크립트가 문구 불일치로 한 번 실패(파일 미변경) → 실제 문구 확인 후 재적용

**변경**
- `docs/local-llm-setup.md`: 1순위 모델을 Ornith-1.5-9B로 교체, 모델 정보 추가. 코드 변경 없음

**검증**
- 문서만. Ollama 태그 이름·실제 크기는 설치 시 확인 필요 (**미검증**)

**다음**
- 집 데스크톱에서 Ornith-1.5-9B로 첫 실호출

## 2026-10-10 — 집 데스크톱 사양 기준 로컬 LLM 구성 결정 및 설치 가이드

**배경**
- 사용자 집 데스크톱 사양 공유: RAM 32GB, AMD Radeon RX 7800 XT (VRAM 16GB)

**과정**
- RX 7800 XT(gfx1101)의 Ollama Windows GPU 지원 여부 확인: 공식 문서(구버전)와 미러·서드파티 자료 모두 지원 목록에 포함.
  최신 공식 Windows 목록은 검색 결과에서 직접 확인하지 못함 → 가이드에 재확인 링크를 남김
- Ornith 크기: 9B Q4 약 6GB(서드파티 자료), 35B A3B Q4 약 21~27GB(추정 사이트, 출처 간 불일치)
  → 9B는 VRAM에 여유 있게 들어가고, 35B는 RAM 오프로드 필요
- Ollama 태그 이름은 검색으로 확인하지 못함 → 라이브러리 검색 또는 `hf.co/` GGUF 직접 받기를 안내
- 주의점 발견: 현재 백엔드는 OpenAI 호환 API를 써서 요청마다 컨텍스트 길이(`num_ctx`)를 지정할 수 없음.
  Ollama 기본 컨텍스트가 작으면 긴 프롬프트가 잘릴 수 있으므로 `OLLAMA_CONTEXT_LENGTH` 서버 설정을 가이드에 포함

**변경**
- `docs/local-llm-setup.md` (신규): 모델 선택표, 설치, 컨텍스트 길이 설정, GPU 사용 확인, 첫 실호출 명령, 문제 해결표
- 결정: 1순위 Ornith 9B 단독으로 1건 실호출 → 이후 다른 계열 모델 추가해 듀얼, 35B A3B는 품질 비교용으로 나중에
- 코드 변경 없음

**검증**
- 문서만. 실제 GPU 인식·속도·태그 이름은 집 데스크톱에서 확인 필요 (**미검증**)

**다음**
- 집 데스크톱에서 가이드 따라 설치 → 첫 실호출 → 결과 공유
- 필요하면 Ollama 네이티브 API(`/api/chat`, 요청별 `num_ctx` 지정 가능) 백엔드 추가 검토

## 2026-10-10 — 생성된 테스트 케이스 CSV 모아보기, 로컬 LLM 연결 일정 결정

**배경**
- 사용자 결정: 로컬 LLM(Ollama) 연결·첫 실호출은 **집 데스크톱에서 진행** (현재 환경은 설치 검토 필요). → 실호출 단계 보류
- 사용자 질문: "생성된 테스트 케이스는 어디서 확인하나?"
  → dry-run만 했으므로 아직 생성된 케이스는 없음. 실호출 시 `output/responses/<target_id>__<model>.json`의 `test_cases`에 저장되지만,
  대상×모델마다 파일이 따로라 사람이 검토하기 불편함을 확인

**과정**
- 원래 계획 4단계("CSV 변환")의 일부를 앞당겨, 검토용으로 전체 케이스를 CSV 하나로 펼치기로 함
- 사용자가 Windows 엑셀로 열 것이므로 한글 깨짐 방지를 위해 UTF-8 BOM(`utf-8-sig`)으로 저장
- 정렬: 파일 → 함수 위치 → 모델 순 (같은 함수에 대한 두 모델의 케이스가 붙어 있어 비교하기 쉽게)

**변경**
- `testgen/report.py` (신규): `write_cases_csv()` — 열: file, function, target_id, model, case_id, technique, priority,
  target_lines, description, preconditions, input, expected
- `testgen/cli.py`: LLM 실행 후 `output/test_cases.csv` 저장 및 경로 출력 (dry-run에서는 생성하지 않음)

**검증**
- 단위 테스트 34개 통과 (신규 1개: 가짜 서버로 실행 → CSV 생성, BOM, 내용 확인)
- **미검증**: 실제 엑셀에서 열었을 때 표시 (사용자 PC), 실제 LLM 응답으로 만든 CSV

**다음**
- (집 데스크톱) Ollama 설치 → `--qualname analyze_work_hours --models local:<모델>`로 첫 실호출 → `test_cases.csv` 검토
- 그 전에 현재 PC에서 `--qualname ... --dry-run`으로 patch 경로 추정 결과 확인 가능

## 2026-10-10 — 함수 지정 실행(`--qualname`) + mock patch 경로 추정

**배경**
- 실제 프로젝트 전체 요약 결과 수신: **갭 267개 → 131개(-51%)**, 대상 함수 107개(변화 없음).
  줄어든 136개는 같은 함수 안에서 빈 줄·여러 줄 문장 때문에 쪼개져 있던 조각 → 직전 개선의 전체 효과 확인
- 첫 LLM 실호출을 `analyze_work_hours` 1개로 시작하려 했으나 `--limit`으로는 특정 함수를 고를 수 없음
- 대상 프로젝트가 `app.` 없이 import(`from services.slack_service import ...`)해서 모델이 patch 경로를 틀릴 위험 (리뷰 6번)

**과정**
- patch 경로는 "파일의 절대 import가 가리키는 최상위 이름(services, utils, models …)이 어느 폴더 아래 실제로 있는가"로
  기준 폴더를 고르는 방식으로 추정. 실제 프로젝트 구조(`backend/app/services`, `from utils.kst import ...`)를
  임시 폴더로 재현해 `services.ai`로 추정되는 것을 확인, 패키지형 import(`from app.utils...`)는 `app.services.ai`로 추정
- 추정이므로 프롬프트에 "추정됩니다"로 명시 (확정은 3단계 실제 실행으로)

**변경**
- `testgen/cli.py`: `--qualname <이름>` (전체 이름 `Class.method` 또는 마지막 이름 `method` 일치)
- `testgen/coverage_extractor.py`: `_guess_module_name()`, `TestTarget.module_name` (targets.json에도 출력)
- `testgen/prompt_builder.py`: 의존성 목록 아래에 patch 경로 예시 (`patch("services.ai_service.get_kst_now")` 형태)

**검증**
- 단위 테스트 33개 통과 (신규 4개: flat import/패키지 import/샘플 픽스처 모듈명 추정, `--qualname` 필터)
- 재현 샘플 dry-run에서 `--qualname summarize`로 1개만 선택되고 patch 경로 문구가 출력되는 것 확인
- **미검증**: 실제 프로젝트에서 `analyze_work_hours`의 추정 결과가 `services.ai_service`로 나오는지, 그 경로로 patch가 실제로 먹는지

**다음**
- 사용자 PC에서 `--qualname analyze_work_hours --dry-run`으로 patch 경로 문구 확인
- 첫 LLM 실호출 모델 선택 (로컬 Ollama / claude -p) — 사용자 결정 대기

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
