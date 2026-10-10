"""LLM이 생성한 테스트 케이스를 사람이 훑어보기 쉬운 CSV 하나로 모은다.

응답 JSON(output/responses/*.json)은 대상×모델마다 파일이 따로 생겨 검토가 불편하므로,
전체 케이스를 한 줄에 하나씩 output/test_cases.csv로 펼친다.
엑셀에서 한글이 깨지지 않도록 UTF-8 BOM(utf-8-sig)으로 저장한다.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from testgen.models import LLMResponse, TestTarget

CSV_COLUMNS = [
    "file",
    "function",
    "target_id",
    "model",
    "case_id",
    "technique",
    "priority",
    "target_lines",
    "description",
    "common_preconditions",
    "preconditions",
    "input",
    "expected",
    "review_note",
]

# 케이스 객체에서 그대로 가져오는 열
CASE_COLUMNS = ["technique", "priority", "target_lines", "description", "preconditions", "input", "expected"]


def write_cases_csv(results: list[tuple[TestTarget, LLMResponse]], path: Path) -> int:
    """케이스를 파일·함수 위치·모델 순으로 정렬해 저장하고, 저장한 케이스 수를 돌려준다."""
    rows = []
    for target, response in sorted(results, key=lambda r: (r[0].file, r[0].start_line, r[1].model)):
        # 파서가 남긴 케이스별 경고(예: "중복 의심: TC-8의 …")를 해당 케이스 줄에 붙인다
        notes: dict[str, list[str]] = {}
        for message in response.parse_errors:
            match = re.match(r"중복 의심: (\S+)의", message)
            if match:
                notes.setdefault(match.group(1), []).append(message)
        for case in response.test_cases:
            rows.append(
                {
                    "file": target.file,
                    "function": target.qualname or "<module>",
                    "target_id": target.target_id,
                    "model": response.model,
                    "case_id": case["id"],
                    "common_preconditions": response.common_preconditions,
                    **{key: case[key] for key in CASE_COLUMNS},
                    "review_note": " / ".join(notes.get(case["id"], [])),
                }
            )
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
