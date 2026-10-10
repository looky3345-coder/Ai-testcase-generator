"""2단계: 커버리지 갭 하나를 ISTQB 기법 기반 테스트케이스 생성 프롬프트로 변환한다."""
from __future__ import annotations

from testgen.models import CoverageGap

_KIND_LABEL = {
    "line": "완전히 실행되지 않은 코드 라인",
    "branch": "일부 분기만 실행되고 나머지 분기는 실행되지 않은 조건문",
}

# 실제 강제/검증 스키마는 testgen.case_parser.TEST_CASES_SCHEMA. 여기는 모델에게 보여줄 설명용 예시.
_OUTPUT_SCHEMA = """{
  "test_cases": [
    {
      "id": "TC-1",
      "technique": "boundary_value_analysis | equivalence_partitioning",
      "description": "무엇을 검증하는 테스트인지 한국어로 간단히",
      "target_lines": "이 테스트가 실행시키는 것으로 예상되는 라인 범위 (예: '45-48')",
      "preconditions": "필요한 사전 상태. 없으면 빈 문자열",
      "input": "테스트에 사용할 구체적인 입력값",
      "expected": "기대 결과 (반환값, 상태 코드, 예외 등)",
      "priority": "high | medium | low"
    }
  ]
}"""

_DEFAULT_FRAMEWORK_HINT = "pytest 기반 테스트 스위트."


def build_prompt(gap: CoverageGap, framework_hint: str | None = None) -> str:
    kind_label = _KIND_LABEL.get(gap.kind, gap.kind)
    location = gap.qualname or f"{gap.file} 모듈 레벨"
    signature = f"\n함수 시그니처: {gap.signature}" if gap.signature else ""
    hint = framework_hint or _DEFAULT_FRAMEWORK_HINT

    return f"""당신은 ISTQB 기법에 정통한 QA 테스트 설계 전문가입니다.
아래는 pytest-cov 커버리지 리포트에서 발견된 미커버 코드 경로입니다.

파일: {gap.file}
대상 함수/메서드: {location}{signature}
갭 종류: {kind_label} (라인 {gap.start_line}-{gap.end_line})

소스 스니펫 ('>>' 로 표시된 라인이 미커버 대상, {gap.snippet_start_line}번 라인부터 시작):
```python
{gap.snippet}
```

프로젝트 컨텍스트: {hint}

요청:
1. 위 미커버 라인/분기를 실제로 실행시킬 수 있는 pytest 테스트 케이스를 제안하세요.
2. 반드시 ISTQB 기법 중 아래 두 가지를 사용하세요.
   - 동등분할(equivalence partitioning): 입력값을 유효/무효 클래스로 나누고 각 클래스 대표값 사용
   - 경계값 분석(boundary value analysis): 유효 범위의 경계, 경계-1, 경계+1 값 사용
3. 이미 커버된 정상 케이스는 제안하지 말고, 지금 미커버 상태인 경로를 실행시키는 케이스만 제안하세요.
4. 각 케이스가 위 스니펫의 어떤 라인을 타겟으로 하는지 target_lines에 명시하세요.

출력 형식: 다른 설명 없이 아래 구조를 따르는 JSON 객체만 출력하세요.
{_OUTPUT_SCHEMA}
"""
