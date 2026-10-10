"""2단계: 테스트 대상(함수 하나와 그 안의 갭들)을 ISTQB 기법 기반 테스트케이스 생성 프롬프트로 변환한다."""
from __future__ import annotations

from testgen.models import TestTarget

# 실제 강제/검증 스키마는 testgen.case_parser.TEST_CASES_SCHEMA. 여기는 모델에게 보여줄 설명용 예시.
_OUTPUT_SCHEMA = """{
  "common_preconditions": "모든 케이스에 공통인 사전조건 (공통 mock/patch와 그 반환값, 공통 DB 상태)",
  "test_cases": [
    {
      "id": "TC-1",
      "technique": "boundary_value_analysis | equivalence_partitioning",
      "description": "무엇을 검증하는 테스트인지 한국어로 간단히",
      "target_lines": "이 테스트가 겨냥하는 미커버 항목의 라인 (예: '45-48' 또는 분기면 '12->15')",
      "preconditions": "이 케이스만의 사전조건 (common_preconditions와 다른 점). 없으면 빈 문자열",
      "input": "테스트에 사용할 구체적인 입력값",
      "expected": "기대 결과 (반환값, 상태 코드, 예외 등)",
      "priority": "high | medium | low"
    }
  ]
}"""

_DEFAULT_FRAMEWORK_HINT = "pytest 기반 테스트 스위트."


def build_prompt(target: TestTarget, framework_hint: str | None = None) -> str:
    location = target.qualname or f"{target.file} 모듈 레벨 코드"
    signature = f"\n함수 시그니처: {target.signature}" if target.signature else ""
    scope = "함수의 일부(갭 주변)" if target.truncated else "함수 전체"
    if target.qualname is None:
        scope = "모듈 레벨 코드 중 갭 주변"
    gap_list = "\n".join(f"- {gap.describe()}" for gap in target.gaps)
    hint = framework_hint or _DEFAULT_FRAMEWORK_HINT

    never_called = ""
    if target.never_called:
        never_called = (
            "\n※ 이 함수는 현재 테스트 스위트에서 한 번도 호출되지 않았습니다. 호출만 해도 대부분의 라인이 실행되므로,"
            "\n  함수 안의 조건문(if/try 등)의 양쪽 경로를 모두 지나도록 케이스를 나누세요.\n"
        )
    dependencies = ""
    if target.dependencies:
        dep_list = "\n".join(f"- {d}" for d in target.dependencies)
        patch_hint = ""
        if target.module_name:
            first = target.dependencies[0].split(":")[0]
            patch_hint = (
                f"\npatch 경로: 이 파일은 `{target.module_name}` 모듈로 import되는 것으로 추정됩니다 (파일의 import 방식 기준)."
                f"\n이 파일이 참조하는 이름을 patch하세요. 예: patch(\"{target.module_name}.{first}\")\n"
            )
        dependencies = f"""
이 코드가 참조하는 모듈 수준 이름과 출처 (테스트에서 준비하거나 mock/patch할 후보):
{dep_list}
{patch_hint}"""
    checklist = ""
    if target.decision_points:
        items = "\n".join(f"- {d}" for d in target.decision_points)
        checklist = f"""
분기·조건 체크리스트 ({len(target.decision_points)}개, 코드에서 자동 추출). 각 항목의 양쪽이 모두 최소 1개 케이스로 실행되어야 합니다:
{items}
"""

    return f"""당신은 ISTQB 기법에 정통한 QA 테스트 설계 전문가입니다.
아래는 pytest-cov 커버리지 리포트에서 발견된 미커버 코드 경로입니다.

파일: {target.file}
대상: {location}{signature}

미커버 항목 ({len(target.gaps)}개):
{gap_list}
{never_called}{dependencies}{checklist}
소스 ({scope}). 줄 앞 표시: '>>' 한 번도 실행되지 않은 라인, 'B>' 일부 분기만 실행된 조건/반복문:
```python
{target.source}
```

프로젝트 컨텍스트: {hint}

요청:
1. 위 미커버 항목을 실제로 실행시킬 수 있는 pytest 테스트 케이스를 제안하세요.
   미커버 라인/분기에 도달하려면 어떤 조건을 통과해야 하는지 소스에서 먼저 파악하세요.
2. 반드시 ISTQB 기법 중 아래 두 가지를 사용하세요.
   - 동등분할(equivalence_partitioning): 입력값을 유효/무효 클래스로 나누고 각 클래스 대표값 사용
   - 경계값 분석(boundary_value_analysis): 미커버 경로로 들어가는 조건식의 경계, 경계-1, 경계+1 값 사용
3. 이미 커버된 정상 경로만 실행하는 케이스는 제안하지 말고, 미커버 항목을 실행시키는 케이스만 제안하세요.
4. 각 케이스가 어떤 미커버 항목·체크리스트 항목을 겨냥하는지 target_lines에 명시하세요. 모든 미커버 항목이 최소 1개 케이스로 다뤄져야 합니다.
5. DB, 외부 API, 현재 시각, 네트워크처럼 실행 환경에 따라 결과가 달라지는 의존성은 mock/patch로 고정하세요.
   무엇을 어떤 값으로 대체하는지 preconditions에 구체적으로 쓰고, expected에는 그 설정에서 결정되는 구체적인 결과를 쓰세요.
   patch할 때는 위에 안내된 patch 경로를 포함한 전체 이름을 preconditions에 쓰세요.
6. 분기·조건 체크리스트가 있으면 모든 항목의 양쪽(참/거짓, 정상/예외, 값 있음/없음, 0회/1회 이상)을 빠짐없이 다루세요.
   케이스 개수를 줄이려고 항목을 건너뛰지 마세요.
7. technique 표기 규칙과 경계값 계산:
   - boundary_value_analysis: 조건식의 경계값 자체 또는 바로 아래/위 값을 입력으로 쓰는 경우에만.
     `< N` 조건이면 N-1(참 쪽 마지막 값)과 N(거짓 쪽 첫 값)이 모두 경계값입니다
   - equivalence_partitioning: 각 구간(클래스)의 대표값을 쓰는 경우 (예: `< 3` 조건에서 0건은 동등분할 대표값, 2건·3건은 경계값)
   - 조건식의 변수가 입력을 변환한 값이면 입력 단위로 환산한 실제 값을 쓰세요
     (예: `minutes = seconds / 60`이고 `minutes <= 10`이면 경계 입력은 599/600/601초. 경계에서 먼 값은 경계값이 아님)
8. try/except가 있으면:
   - 정상 완료 쪽 케이스를 최소 1개 포함하세요. 이때 mock 반환값은 코드 안의 대체(fallback) 문자열과 다른, 구분 가능한 값으로 하세요
   - 예외(side_effect)는 except 경로를 겨냥한 케이스에만 쓰세요. 다른 분기를 시험하는 케이스까지 모두 예외로 만들지 마세요
9. 각 필드는 간결하게 쓰세요 (description·preconditions·input·expected 각각 한두 문장) — 출력이 길면 중간에 잘립니다.
   모든 케이스에 공통인 mock/patch는 common_preconditions에 한 번만 쓰고, 케이스별 preconditions에는 다른 점만 쓰세요.
   각 케이스는 common_preconditions + 자기 preconditions만으로 실행 가능해야 합니다. 필요한 mock이 어디에도 없으면 안 됩니다
   (예: 외부 API를 부르는 함수를 mock하지 않으면 테스트가 실제 API를 호출합니다).
10. 분기의 효과가 반환값에 드러나지 않고 mock에 넘기는 인자에만 드러나면(예: 조건에 따라 만들어진 문자열을 외부 함수에 전달),
   expected에 반환값뿐 아니라 그 mock의 호출 인자 검증을 쓰세요 (예: "전달된 인자에 '<조건에 따라 추가되는 문구>'가 포함됨").
   반환값만으로는 어느 분기를 탔는지 구분할 수 없는 테스트는 분기 로직이 틀려도 통과합니다.
11. 입력·사전조건이 같은 케이스를 중복으로 만들지 마세요. 한 케이스가 여러 체크리스트 항목을 함께 다뤄도 됩니다.

출력 형식: 다른 설명 없이 아래 구조를 따르는 JSON 객체만 출력하세요.
{_OUTPUT_SCHEMA}
"""
