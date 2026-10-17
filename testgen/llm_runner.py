"""LLM 백엔드: 프롬프트를 보내고 응답 원문을 회수한다.

- CLIBackend: `claude -p`, `codex exec -` 처럼 stdin으로 프롬프트를 받는 CLI (유료 구독/API)
- OpenAICompatBackend: Ollama, llama.cpp server, LM Studio, vLLM 등
  OpenAI 호환 `/chat/completions` API를 제공하는 로컬 런타임 (무과금)
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

from testgen.config import CLI_BACKENDS, LLM_TIMEOUT_SEC, LOCAL_TIMEOUT_SEC
from testgen.models import LLMResponse


class LLMBackend:
    name: str

    def run(self, target_id: str, prompt: str, structured: bool = True) -> LLMResponse:
        """structured=False면 출력 형식(JSON 스키마) 강제 없이 자유 텍스트로 받는다 (테스트 코드 생성용)."""
        raise NotImplementedError

    def check_model(self) -> str | None:
        """호출 전 사전 점검. 문제가 있으면 사용자에게 보여줄 오류 메시지, 없거나 점검할 수 없으면 None."""
        return None


class CLIBackend(LLMBackend):
    def __init__(self, name: str, command: list[str], timeout: int = LLM_TIMEOUT_SEC):
        self.name = name
        # Windows에서 npm 글로벌 설치 CLI는 대부분 .cmd 쉼(shim)이라 shell=False인
        # subprocess는 이를 못 찾는다. shutil.which로 PATHEXT까지 감안해 실제 경로를 찾는다.
        resolved = shutil.which(command[0])
        self.command = [resolved or command[0], *command[1:]]
        self.timeout = timeout

    def run(self, target_id: str, prompt: str, structured: bool = True) -> LLMResponse:
        start = time.monotonic()

        def fail(error: str, raw_output: str = "") -> LLMResponse:
            return LLMResponse(
                model=self.name,
                target_id=target_id,
                ok=False,
                raw_output=raw_output,
                error=error,
                elapsed_sec=time.monotonic() - start,
                command=self.command,
            )

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
            return fail(f"'{self.command[0]}' 실행 파일을 찾을 수 없습니다 (PATH 확인 필요)")
        except subprocess.TimeoutExpired:
            return fail(f"{self.timeout}초 타임아웃")

        if proc.returncode != 0:
            # 일부 CLI는 에러 메시지를 stderr가 아니라 stdout에 낸다 (예: claude -p 인증 오류).
            detail = (proc.stderr or "").strip() or (proc.stdout or "").strip()
            return fail(f"exit code {proc.returncode}: {detail[:500]}", proc.stdout or "")

        return LLMResponse(
            model=self.name,
            target_id=target_id,
            ok=True,
            raw_output=proc.stdout or "",
            error=None,
            elapsed_sec=time.monotonic() - start,
            command=self.command,
        )


class OpenAICompatBackend(LLMBackend):
    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        timeout: int = LOCAL_TIMEOUT_SEC,
        response_schema: dict | None = None,
        api_key: str | None = None,
        temperature: float = 0.2,
        thinking: bool = False,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.url = self.base_url + "/chat/completions"
        self.model = model
        self.timeout = timeout
        self.response_schema = response_schema
        self.api_key = api_key
        self.temperature = temperature
        # 추론형 모델(Ornith/Qwen 계열 등)은 Ollama에서 사고 과정을 별도 `reasoning` 필드로 내보내고
        # 정작 `content`가 비는 경우가 있다 (실제 사례: 46초 생성 후 content 빈 응답). 기본은 사고 과정을 끈다.
        self.thinking = thinking

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def check_model(self) -> str | None:
        """`GET /models`로 런타임에 이 모델이 있는지 확인한다. 이름이 틀리면 대상 수만큼 404가 반복되므로 미리 막는다.
        `/models`를 지원하지 않는 런타임이면 점검을 건너뛴다 (None)."""
        request = urllib.request.Request(self.base_url + "/models", headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                models = [m["id"] for m in json.loads(resp.read().decode("utf-8"))["data"]]
        except urllib.error.HTTPError:
            return None
        except urllib.error.URLError as exc:
            return f"{self.base_url} 연결 실패 ({exc.reason}) — 로컬 런타임(예: Ollama)이 실행 중인지 확인"
        except (json.JSONDecodeError, KeyError, TypeError, socket.timeout, TimeoutError):
            return None

        # Ollama는 태그 없는 이름을 ':latest'로 취급한다
        candidates = {self.model, f"{self.model}:latest"}
        if self.model.endswith(":latest"):
            candidates.add(self.model[: -len(":latest")])
        if candidates & set(models):
            return None
        available = ", ".join(models) if models else "(없음)"
        return (
            f"모델 '{self.model}'이(가) {self.base_url} 에 없습니다.\n"
            f"  사용 가능한 모델: {available}\n"
            f"  `ollama list`의 NAME을 --models \"local:<NAME>\"에 그대로 쓰거나, `ollama cp <NAME> <별칭>`으로 별칭을 만드세요."
        )

    def _request_body(self, prompt: str, structured: bool = True) -> dict:
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "stream": False,
        }
        if not self.thinking:
            # Ollama의 OpenAI 호환 API는 reasoning_effort "none"을 사고 과정 끄기로 처리한다
            body["reasoning_effort"] = "none"
        if structured and self.response_schema is not None:
            # 지원 런타임에서는 문법 제약 디코딩으로 스키마를 벗어난 출력 자체가 나오지 않는다
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "test_cases", "schema": self.response_schema, "strict": True},
            }
        return body

    def run(self, target_id: str, prompt: str, structured: bool = True) -> LLMResponse:
        start = time.monotonic()
        command = ["POST", self.url, f"model={self.model}"]

        def fail(error: str, raw_output: str = "") -> LLMResponse:
            return LLMResponse(
                model=self.name,
                target_id=target_id,
                ok=False,
                raw_output=raw_output,
                error=error,
                elapsed_sec=time.monotonic() - start,
                command=command,
            )

        request = urllib.request.Request(
            self.url,
            data=json.dumps(self._request_body(prompt, structured)).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            return fail(f"HTTP {exc.code}: {detail[:500]}")
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                return fail(f"{self.timeout}초 타임아웃")
            return fail(f"{self.url} 연결 실패 ({exc.reason}) — 로컬 런타임(예: `ollama serve`)이 실행 중인지 확인")
        except (TimeoutError, socket.timeout):
            return fail(f"{self.timeout}초 타임아웃")

        try:
            payload = json.loads(body)
            choice = payload["choices"][0]
            usage = payload.get("usage") or {}
            content = choice["message"].get("content")
            reasoning = choice["message"].get("reasoning") or choice["message"].get("reasoning_content") or ""
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError):
            return fail("응답 형식이 OpenAI chat completions 형식이 아닙니다", body)

        return LLMResponse(
            model=self.name,
            target_id=target_id,
            ok=True,
            raw_output=content or "",
            error=None,
            elapsed_sec=time.monotonic() - start,
            command=command,
            # "length"면 출력/컨텍스트 한도로 응답이 잘린 것
            finish_reason=choice.get("finish_reason"),
            # 본문이 비었거나 파싱이 안 될 때 원인(별도 reasoning 필드 등)을 볼 수 있도록 원본 HTTP 응답도 보관
            raw_response=body,
            reasoning=reasoning,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )


def _safe_name(name: str) -> str:
    """응답 파일명에 쓰이므로 Windows에서 금지된 문자(':' 등)를 치환한다."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def build_backends(
    specs: list[str],
    local_base_url: str,
    response_schema: dict | None = None,
    local_api_key: str | None = None,
    local_thinking: bool = False,
) -> list[LLMBackend]:
    """`--models` 항목(claude, codex, local:<모델명>)을 백엔드 객체로 만든다. 잘못된 항목은 ValueError."""
    backends: list[LLMBackend] = []
    for spec in specs:
        if spec in CLI_BACKENDS:
            backends.append(CLIBackend(spec, CLI_BACKENDS[spec]))
        elif spec.startswith("local:") and spec[len("local:"):]:
            model = spec[len("local:"):]  # Ollama 태그의 ':'(예: qwen3:8b)는 그대로 둔다
            backends.append(
                OpenAICompatBackend(
                    _safe_name(f"local-{model}"),
                    local_base_url,
                    model,
                    response_schema=response_schema,
                    api_key=local_api_key,
                    thinking=local_thinking,
                )
            )
        else:
            raise ValueError(f"알 수 없는 모델 지정: '{spec}' (claude, codex, local:<모델명> 중 하나)")

    names = [b.name for b in backends]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        raise ValueError(f"같은 모델이 중복 지정됨: {duplicated}")
    return backends
