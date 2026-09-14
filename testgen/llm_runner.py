"""claude -p / codex -p 를 서브프로세스로 호출해서 프롬프트를 던지고 결과를 회수한다."""
from __future__ import annotations

import shutil
import subprocess
import time

from testgen.config import LLM_TIMEOUT_SEC
from testgen.models import LLMResponse


class LLMRunner:
    def __init__(self, name: str, command: list[str], timeout: int = LLM_TIMEOUT_SEC):
        self.name = name
        # Windows에서 npm 글로벌 설치 CLI는 대부분 .cmd 쉼(shim)이라 shell=False인
        # subprocess는 이를 못 찾는다. shutil.which로 PATHEXT까지 감안해 실제 경로를 찾는다.
        resolved = shutil.which(command[0])
        self.command = [resolved or command[0], *command[1:]]
        self.timeout = timeout

    def run(self, gap_id: str, prompt: str) -> LLMResponse:
        start = time.monotonic()
        try:
            proc = subprocess.run(
                self.command,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout,
            )
        except FileNotFoundError:
            return LLMResponse(
                model=self.name,
                gap_id=gap_id,
                ok=False,
                raw_output="",
                error=f"'{self.command[0]}' 실행 파일을 찾을 수 없습니다 (PATH 확인 필요)",
                elapsed_sec=time.monotonic() - start,
                command=self.command,
            )
        except subprocess.TimeoutExpired:
            return LLMResponse(
                model=self.name,
                gap_id=gap_id,
                ok=False,
                raw_output="",
                error=f"{self.timeout}초 타임아웃",
                elapsed_sec=time.monotonic() - start,
                command=self.command,
            )

        elapsed = time.monotonic() - start
        if proc.returncode != 0:
            # 일부 CLI는 에러 메시지를 stderr가 아니라 stdout에 낸다 (예: claude -p 인증 오류).
            detail = (proc.stderr or "").strip() or (proc.stdout or "").strip()
            return LLMResponse(
                model=self.name,
                gap_id=gap_id,
                ok=False,
                raw_output=proc.stdout or "",
                error=f"exit code {proc.returncode}: {detail[:500]}",
                elapsed_sec=elapsed,
                command=self.command,
            )

        return LLMResponse(
            model=self.name,
            gap_id=gap_id,
            ok=True,
            raw_output=proc.stdout or "",
            error=None,
            elapsed_sec=elapsed,
            command=self.command,
        )
