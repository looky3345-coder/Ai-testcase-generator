# 2026-10-10 첫 LLM 생성 케이스 품질 검토

대상: `analyze_work_hours` (Checkine-Automation-Project `app/services/ai_service.py`)
모델: Ornith-1.5-9B Q4_K_M (Ollama, 집 데스크톱 RX 7800 XT), thinking off
결과: 9.4초, 입력 1,843 / 출력 527 토큰, `finish_reason=stop`, JSON 스키마 검증 통과, 케이스 2개

## 생성된 케이스

| ID | 기법(모델 표기) | 내용 |
|---|---|---|
| TC-1 | boundary_value_analysis | DONE 기록 0건 → 조기 반환 문구 |
| TC-2 | equivalence_partitioning | DONE 기록 3건, 100000초 → generate_with_retry mock 반환값(=fallback 문구) |

## 평가

**좋은 점**
- 형식·스키마 완벽 준수, 두 주요 경로(조기 반환 / 전체 경로)는 구분
- 의존성 목록을 활용해 mock 대상을 대부분 맞게 식별

**문제점**

| # | 문제 | 근거 |
|---|---|---|
| 1 | 기법 라벨 오류 | `< 3`의 경계는 2/3인데 0건을 BVA로, 경계값인 3건을 EP로 표기 |
| 2 | 조건 한쪽 누락 | `hours <= 5` 참 경로(124줄) 미실행 — 입력이 100000초(27.8h)뿐. 경계는 17999/18000/18001초 |
| 3 | 예외 경로 착시 | mock 반환값을 fallback 문구로 설정 → except(148-150줄) 미실행인데 expected는 우연히 일치 |
| 4 | 동등분할 누락 | Slack 결과 None / DND True·False, status_text 유무, work_seconds None 기록 |
| 5 | 잘못된 mock 대상 | `Session`(타입 표기용)을 patch 대상으로 지정, patch 전체 경로 미기재 |
| 6 | 케이스 수 부족 | 2개. 분기 지점(8개)의 양쪽을 다루려면 최소 8~10개 필요 |

## 원인 판단

소형 모델이 "조건문 양쪽을 모두", "경계값 사용" 같은 **추상 지시를 구체 목록으로 풀어내지 못함**.
분기 지점과 경계 후보는 AST로 결정적으로 뽑을 수 있으므로, 모델의 추론에 맡기지 않고 프롬프트에 체크리스트로 제공한다.

## 조치 (같은 날 반영)

- 분기·조건 체크리스트 자동 추출: if/while(비교 상수 → 경계값 후보), 삼항, `x or 기본값`, try/except, for(0회/1회 이상)
  → 실제 함수에서 8개 항목 추출 확인 (`tests/fixtures/real_excerpts/analyze_work_hours.py`)
- 타입 표기에만 쓰인 의존성에 "mock 불필요" 표시 (문제 5)
- 프롬프트 규칙 추가: 체크리스트 전 항목 양쪽 커버(문제 2·4·6), technique 표기 기준과 예시(문제 1),
  예외 경로는 side_effect·fallback과 같은 반환값 금지(문제 3), patch 전체 경로 기재(문제 5)

## 남은 확인

- 개선된 프롬프트로 같은 함수 재실행 → 위 6개 문제가 줄었는지 비교
- 프롬프트가 길어져(체크리스트) 소형 모델의 출력 품질·속도에 미치는 영향

## 2차 결과 (체크리스트 + 16K 컨텍스트)

모델 별칭 `ornith15-9b-16k`(Modelfile num_ctx 16384), 57.4초, 입력 2,494 + 출력 3,222 = 5,716 토큰, `finish_reason=stop`, 케이스 12개

| # | 1차 문제 | 2차 결과 |
|---|---|---|
| 1 | 기법 라벨 오류 | △ 3·4건은 BVA로 맞음. 2건(TC-1)은 경계값인데 EP로 표기 |
| 2 | `hours <= 5` 참 경로 누락 | △ 참 경로는 실행(TC-4, 10000초). 경계 입력 17999/18000/18001초는 미사용인데 BVA로 표기 |
| 3 | 예외 경로 착시 | ✅ side_effect 사용. 단 과교정(아래 A) |
| 4 | 동등분할 누락 | ✅ 대부분 해결 (Slack None, DND T/F, status_text 유/무). `work_seconds or 0`의 None 쪽만 누락 |
| 5 | 잘못된 mock 대상 | ✅ `patch('services.ai_service.…')` 전체 경로, Session 미사용 |
| 6 | 케이스 수 부족 | ✅ 12개 |

**새 문제**

| | 문제 | 영향 |
|---|---|---|
| A | TC-2~12 전부 generate_with_retry를 예외로 설정 | try 정상 완료 경로 미검증 |
| B | 분기별 케이스의 expected가 모두 같은 fallback 문자열 | 분기 효과는 generate_with_retry에 넘기는 prompt 문자열에만 드러남 → 반환값만 검증하면 분기 로직이 틀려도 통과 (테스트 오라클 문제) |
| C | TC-6=TC-8, TC-7=TC-9 (입력·사전조건 동일) | 중복 |
| D | target_lines 표기가 `108->107`처럼 역방향·부정확 | 추적성 저하 (검토용이라 우선순위 낮음) |

**조치 (같은 날 반영)**
- 규칙 7 보강: `< N`이면 N-1·N 모두 경계값, 변환된 변수는 입력 단위로 환산한 실제 경계값 사용
- 규칙 8 재작성: 정상 완료 케이스 최소 1개(fallback과 구분되는 반환값), 예외는 except 겨냥 케이스에만
- 규칙 10: 분기 효과가 mock 호출 인자에만 드러나면 expected에 호출 인자 검증 (B)
- 규칙 11: 중복 금지 + 파서가 입력·사전조건 동일 케이스를 "중복 의심"으로 표시, CSV `review_note` 열 (C)
- D는 3단계(실행·커버리지 측정)에서 실제 커버 라인으로 대체 가능하므로 보류
