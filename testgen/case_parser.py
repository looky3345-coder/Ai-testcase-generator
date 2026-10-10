"""LLM 응답 원문에서 테스트 케이스 JSON을 꺼내고 스키마대로 검증한다.

로컬 런타임(OpenAI 호환 API)에는 TEST_CASES_SCHEMA를 그대로 넘겨 출력 형식을 강제하고,
형식 강제가 안 되는 CLI 백엔드(claude/codex)는 여기서 코드펜스·앞뒤 설명을 걷어내고 파싱한다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

TECHNIQUES = ("boundary_value_analysis", "equivalence_partitioning")
PRIORITIES = ("high", "medium", "low")
STRING_FIELDS = ("id", "description", "target_lines", "preconditions", "input", "expected")

TEST_CASES_SCHEMA = {
    "type": "object",
    "properties": {
        "test_cases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    **{name: {"type": "string"} for name in STRING_FIELDS},
                    "technique": {"type": "string", "enum": list(TECHNIQUES)},
                    "priority": {"type": "string", "enum": list(PRIORITIES)},
                },
                "required": [*STRING_FIELDS, "technique", "priority"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["test_cases"],
    "additionalProperties": False,
}

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
# 추론형 모델(Qwen 계열 기반 등)이 답 앞에 붙이는 사고 과정 블록
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class ParseResult:
    test_cases: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _load_json(raw: str):
    """원문에서 첫 JSON 값을 찾아 로드한다. 못 찾으면 ValueError."""
    text = _THINK_RE.sub("", raw).strip()
    if not text:
        raise ValueError("모델 응답 본문이 비어 있습니다" + (" (사고 과정 <think>만 있고 답이 없음)" if raw.strip() else ""))
    if re.match(r"<think>", text, re.IGNORECASE):
        raise ValueError("사고 과정(<think>)이 닫히기 전에 응답이 끝났습니다 — 출력이 잘렸을 가능성")
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 앞뒤에 설명 문장이 붙은 경우: 첫 '{' 또는 '['부터 디코딩을 시도한다
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                value, _ = decoder.raw_decode(text, i)
                return value
            except json.JSONDecodeError:
                continue
    raise ValueError("응답에서 JSON을 찾을 수 없습니다")


def _validate_case(index: int, case) -> list[str]:
    if not isinstance(case, dict):
        return [f"케이스 #{index}: 객체가 아님"]
    errors = []
    for name in STRING_FIELDS:
        if not isinstance(case.get(name), str):
            errors.append(f"케이스 #{index}: '{name}' 누락 또는 문자열 아님")
    if case.get("technique") not in TECHNIQUES:
        errors.append(f"케이스 #{index}: technique 값 오류 ({case.get('technique')!r})")
    if case.get("priority") not in PRIORITIES:
        errors.append(f"케이스 #{index}: priority 값 오류 ({case.get('priority')!r})")
    return errors


def parse_test_cases(raw: str) -> ParseResult:
    """유효한 케이스만 test_cases에 담고, 버린 이유는 errors에 남긴다."""
    try:
        data = _load_json(raw)
    except ValueError as exc:
        return ParseResult(errors=[str(exc)])

    # 예전 프롬프트(최상위 배열) 응답도 받아준다
    if isinstance(data, dict) and isinstance(data.get("test_cases"), list):
        cases = data["test_cases"]
    elif isinstance(data, list):
        cases = data
    else:
        return ParseResult(errors=["최상위에 'test_cases' 배열이 없습니다"])

    result = ParseResult()
    for index, case in enumerate(cases, start=1):
        case_errors = _validate_case(index, case)
        if case_errors:
            result.errors.extend(case_errors)
        else:
            result.test_cases.append(case)
    return result
