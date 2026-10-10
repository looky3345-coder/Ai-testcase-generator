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
