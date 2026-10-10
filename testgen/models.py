"""커버리지 갭 / 테스트 대상 / LLM 응답 데이터 모델."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


@dataclass
class CoverageGap:
    """미커버 코드 경로 하나: 연속된 미실행 라인 구간, 또는 실행되지 않은 분기 하나."""

    file: str  # source_root 기준 상대경로 (posix 구분자)
    kind: str  # "line" | "branch"
    start_line: int  # line: 구간 시작 / branch: 분기 출발 라인
    end_line: int  # line: 구간 끝 / branch: start_line과 같음
    qualname: str | None  # 감싸는 함수/메서드 이름 (예: ClassA.method), 모듈 레벨이면 None
    # branch 전용: 실행되지 않은 분기의 도착 라인. 음수면 코드 객체를 빠져나가는 분기
    # (coverage.py 규칙: -N은 N번 라인에서 시작하는 함수/모듈의 종료)
    branch_target: int | None = None

    @property
    def gap_id(self) -> str:
        if self.kind == "branch":
            return _short_hash(f"{self.file}:branch:{self.start_line}->{self.branch_target}")
        return _short_hash(f"{self.file}:{self.kind}:{self.start_line}-{self.end_line}")

    def describe(self) -> str:
        """프롬프트에 넣을 한 줄 설명."""
        if self.kind == "branch":
            if self.branch_target is not None and self.branch_target < 0:
                dest = "함수/모듈을 빠져나가는 경로"
            else:
                dest = f"라인 {self.branch_target}(으)로 가는 경로"
            return f"라인 {self.start_line}의 분기: {dest}가 한 번도 실행되지 않음"
        if self.start_line == self.end_line:
            return f"라인 {self.start_line}: 한 번도 실행되지 않음"
        return f"라인 {self.start_line}-{self.end_line}: 한 번도 실행되지 않음"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["gap_id"] = self.gap_id
        return d


@dataclass
class TestTarget:
    """LLM 호출 1건의 단위: 함수 하나(또는 파일의 모듈 레벨 코드)와 그 안의 갭 전부."""

    __test__ = False  # pytest가 테스트 클래스로 수집하지 않도록

    file: str
    qualname: str | None  # None이면 모듈 레벨 코드
    start_line: int  # 함수 시작(데코레이터 포함) 라인, 모듈 레벨이면 첫 갭 라인
    signature: str | None
    source: str  # 라인 번호와 마커('>>' 미실행, 'B>' 일부 분기 미실행)가 붙은 소스
    truncated: bool  # 함수가 길어 갭 주변만 잘라 보여줬는지
    gaps: list[CoverageGap] = field(default_factory=list)
    never_called: bool = False  # 테스트가 이 함수를 한 번도 호출하지 않음 (본문 실행 라인 0개)
    # 함수가 참조하는 모듈 수준 이름과 출처 (예: "get_kst_now: from utils import get_kst_now") — mock 후보
    dependencies: list[str] = field(default_factory=list)
    module_name: str | None = None  # 테스트 실행 시 import되는 모듈 이름 추정 (mock.patch 경로용)

    @property
    def target_id(self) -> str:
        # 같은 이름 함수(property getter/setter 등) 구분을 위해 시작 라인 포함
        name = self.qualname or "<module>"
        return _short_hash(f"{self.file}:{name}:{self.start_line if self.qualname else 0}")

    def to_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "file": self.file,
            "qualname": self.qualname,
            "start_line": self.start_line,
            "signature": self.signature,
            "truncated": self.truncated,
            "never_called": self.never_called,
            "dependencies": self.dependencies,
            "module_name": self.module_name,
            "source": self.source,
            "gaps": [g.to_dict() for g in self.gaps],
        }


@dataclass
class LLMResponse:
    """LLM 호출 1건의 결과."""

    model: str
    target_id: str
    ok: bool
    raw_output: str
    error: str | None
    elapsed_sec: float
    command: list[str] = field(default_factory=list)
    test_cases: list[dict] = field(default_factory=list)  # 스키마 검증을 통과한 케이스
    parse_errors: list[str] = field(default_factory=list)  # 파싱 실패/버린 케이스 사유
    finish_reason: str | None = None  # OpenAI 호환 응답의 종료 사유 ("stop", "length" 등)
    raw_response: str = ""  # 원본 HTTP 응답 본문 (진단용, OpenAI 호환 백엔드만)
    reasoning: str = ""  # 추론형 모델이 별도 필드로 내보낸 사고 과정 (있을 때만)

    def to_dict(self) -> dict:
        return asdict(self)
