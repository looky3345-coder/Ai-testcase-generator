"""AI 테스트케이스 생성 파이프라인 공통 설정.

이 도구는 완전히 독립된 프로젝트다. 분석 대상 프로젝트(coverage.json, 소스 루트)는
런타임에 CLI 인자로 받으며, 이 파일에는 도구 자체의 기본값만 둔다.
"""
import os
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parents[1]  # ai-testgen/

DEFAULT_OUTPUT_DIR = TOOL_ROOT / "output"

# 프롬프트에 함수 전체를 넣는 최대 길이. 이보다 길면 헤더(데코레이터+시그니처)와 갭 주변만 넣는다
MAX_FUNCTION_LINES = 120
# 긴 함수를 잘라 보여줄 때 갭 앞뒤로 붙일 라인 수
LONG_FUNCTION_CONTEXT_LINES = 8
# 모듈 레벨(함수 밖) 갭 앞뒤로 붙일 라인 수
MODULE_CONTEXT_LINES = 5

# 유료 CLI 백엔드 호출 커맨드. 프롬프트는 stdin으로 전달한다.
# - claude: `claude -p`가 표준 비대화형(print) 모드, stdin 프롬프트 지원
# - codex: `codex exec -`가 비대화형 실행 + "-"로 stdin 전체를 프롬프트로 사용
#   (OpenAI 공식 문서 확인: https://learn.chatgpt.com/docs/non-interactive-mode)
CLI_BACKENDS = {
    "claude": ["claude", "-p"],
    "codex": ["codex", "exec", "-"],
}

LLM_TIMEOUT_SEC = 180

# 무과금 로컬 백엔드 (`--models local:<모델명>`). OpenAI 호환 API 기준 URL.
# 기본값은 Ollama. llama.cpp server는 http://localhost:8080/v1, LM Studio는 http://localhost:1234/v1
DEFAULT_LOCAL_BASE_URL = os.environ.get("TESTGEN_LOCAL_BASE_URL", "http://localhost:11434/v1")
# 로컬 런타임은 대부분 키가 필요 없다. vLLM 등에서 --api-key를 걸었을 때만 사용
LOCAL_API_KEY = os.environ.get("TESTGEN_LOCAL_API_KEY")
# 로컬 모델은 CPU 추론 시 느리므로 CLI보다 넉넉하게 둔다
LOCAL_TIMEOUT_SEC = 600
