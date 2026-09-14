"""AI 테스트케이스 생성 파이프라인 공통 설정.

이 도구는 완전히 독립된 프로젝트다. 분석 대상 프로젝트(coverage.json, 소스 루트)는
런타임에 CLI 인자로 받으며, 이 파일에는 도구 자체의 기본값만 둔다.
"""
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parents[1]  # ai-testgen/

DEFAULT_OUTPUT_DIR = TOOL_ROOT / "output"
DEFAULT_GAPS_FILE = DEFAULT_OUTPUT_DIR / "gaps.json"
DEFAULT_RESPONSES_DIR = DEFAULT_OUTPUT_DIR / "responses"
DEFAULT_PROMPTS_DIR = DEFAULT_OUTPUT_DIR / "prompts"

# 갭 하나의 소스 스니펫 앞뒤로 붙일 여유 라인 수
SNIPPET_CONTEXT_LINES = 2

# 두 LLM CLI 호출 커맨드. 프롬프트는 stdin으로 전달한다.
# 로컬에 설치된 codex 버전의 비대화형 실행 플래그가 다르면 여기만 수정하면 된다.
# (이 환경에는 codex CLI가 설치돼 있지 않아 직접 검증하지 못했다.)
LLM_RUNNERS = {
    "claude": ["claude", "-p"],
    "codex": ["codex", "-p"],
}

LLM_TIMEOUT_SEC = 180
