"""2단계: 테스트 대상(함수 하나와 그 안의 갭들)을 ISTQB 기법 기반 테스트케이스 생성 프롬프트로 변환한다."""
from __future__ import annotations

from testgen.models import TestTarget

# 실제 강제/검증 스키마는 testgen.case_parser.TEST_CASES_SCHEMA. 여기는 모델에게 보여줄 설명용 예시.
_OUTPUT_SCHEMA = """{
  "test_cases": [
    {
      "id": "TC-1",
      "technique": "boundary_value_analysis | equivalence_partitioning",
      "description": "무엇을 검증하는 테스트인지 한국어로 간단히",
      "target_lines": "이 테스트가 겨냥하는 미커버 항목의 라인 (예: '45-48' 또는 분기면 '12->15')",
      "preconditions": "필요한 사전 상태. 없으면 빈 문자열",
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

    return f"""당신은 ISTQB 기법에 정통한 QA 테스트 설계 전문가입니다.
아래는 pytest-cov 커버리지 리포트에서 발견된 미커버 코드 경로입니다.

파일: {target.file}
대상: {location}{signature}

미커버 항목 ({len(target.gaps)}개):
{gap_list}
{never_called}{dependencies}
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
4. 각 케이스가 어떤 미커버 항목을 겨냥하는지 target_lines에 명시하세요. 모든 미커버 항목이 최소 1개 케이스로 다뤄져야 합니다.
5. DB, 외부 API, 현재 시각, 네트워크처럼 실행 환경에 따라 결과가 달라지는 의존성은 mock/patch로 고정하세요.
   무엇을 어떤 값으로 대체하는지 preconditions에 구체적으로 쓰고, expected에는 그 설정에서 결정되는 구체적인 결과를 쓰세요.

출력 형식: 다른 설명 없이 아래 구조를 따르는 JSON 객체만 출력하세요.
{_OUTPUT_SCHEMA}
"""
