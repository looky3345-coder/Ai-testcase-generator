"""커버리지 갭 / LLM 응답 데이터 모델."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict


@dataclass
class CoverageGap:
    """미커버 코드 경로 하나 (연속된 라인 구간, 또는 브랜치 포인트)."""

    file: str  # source_root 기준 상대경로 (posix 구분자)
    kind: str  # "line" | "branch"
    start_line: int
    end_line: int
    qualname: str | None  # 감싸는 함수/메서드 이름 (예: ClassA.method)
    signature: str | None
    snippet: str  # 라인 번호가 붙은 소스 스니펫
    snippet_start_line: int

    @property
    def gap_id(self) -> str:
        digest = hashlib.sha1(
            f"{self.file}:{self.kind}:{self.start_line}-{self.end_line}".encode("utf-8")
        ).hexdigest()[:10]
        return digest

    def to_dict(self) -> dict:
        d = asdict(self)
        d["gap_id"] = self.gap_id
        return d


@dataclass
class LLMResponse:
    """LLM CLI 호출 1건의 결과."""

    model: str
    gap_id: str
    ok: bool
    raw_output: str
    error: str | None
    elapsed_sec: float
    command: list[str] = field(default_factory=list)
    test_cases: list[dict] = field(default_factory=list)  # 스키마 검증을 통과한 케이스
    parse_errors: list[str] = field(default_factory=list)  # 파싱 실패/버린 케이스 사유

    def to_dict(self) -> dict:
        return asdict(self)
