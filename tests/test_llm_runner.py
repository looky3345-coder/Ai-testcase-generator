import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from testgen.case_parser import TEST_CASES_SCHEMA
from testgen.llm_runner import CLIBackend, OpenAICompatBackend, build_backends


class _FakeOpenAIServer:
    """/v1/chat/completions 를 흉내 내는 로컬 HTTP 서버. 받은 요청 본문을 기록한다."""

    def __init__(self, status=200, content='{"test_cases": []}', raw_body=None, models=None):
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                # models=None이면 /models 미지원 런타임처럼 404
                if models is None or self.path != "/v1/models":
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps({"object": "list", "data": [{"id": m, "object": "model"} for m in models]})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                outer.requests.append({"path": self.path, "body": json.loads(self.rfile.read(length))})
                body = raw_body if raw_body is not None else json.dumps(
                    {"choices": [{"message": {"role": "assistant", "content": content}}]}
                )
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class OpenAICompatBackendTest(unittest.TestCase):
    def test_success_sends_schema_and_returns_content(self):
        fake = _FakeOpenAIServer(content='{"test_cases": [1]}')
        self.addCleanup(fake.close)
        backend = OpenAICompatBackend("local-m", fake.base_url, "qwen3:8b", response_schema=TEST_CASES_SCHEMA)

        response = backend.run("t1", "프롬프트")

        self.assertTrue(response.ok, response.error)
        self.assertEqual(response.raw_output, '{"test_cases": [1]}')
        request = fake.requests[0]
        self.assertEqual(request["path"], "/v1/chat/completions")
        self.assertEqual(request["body"]["model"], "qwen3:8b")
        self.assertEqual(request["body"]["messages"][0]["content"], "프롬프트")
        self.assertEqual(request["body"]["response_format"]["json_schema"]["schema"], TEST_CASES_SCHEMA)

    def test_finish_reason_and_raw_response_kept(self):
        body = json.dumps({"choices": [{"message": {"content": None, "reasoning": "생각"}, "finish_reason": "length"}]})
        fake = _FakeOpenAIServer(raw_body=body)
        self.addCleanup(fake.close)
        response = OpenAICompatBackend("local-m", fake.base_url, "m").run("t1", "p")
        self.assertTrue(response.ok)
        self.assertEqual(response.raw_output, "")
        self.assertEqual(response.finish_reason, "length")
        self.assertIn("reasoning", response.raw_response)

    def test_thinking_off_by_default_and_reasoning_captured(self):
        body = json.dumps({"choices": [{"message": {"content": "", "reasoning": "긴 사고 과정"}, "finish_reason": "stop"}]})
        fake = _FakeOpenAIServer(raw_body=body)
        self.addCleanup(fake.close)
        response = OpenAICompatBackend("local-m", fake.base_url, "m").run("t1", "p")
        self.assertEqual(fake.requests[0]["body"]["reasoning_effort"], "none")
        self.assertEqual(response.reasoning, "긴 사고 과정")

    def test_thinking_on_omits_reasoning_effort(self):
        fake = _FakeOpenAIServer()
        self.addCleanup(fake.close)
        OpenAICompatBackend("local-m", fake.base_url, "m", thinking=True).run("t1", "p")
        self.assertNotIn("reasoning_effort", fake.requests[0]["body"])

    def test_http_error(self):
        fake = _FakeOpenAIServer(status=404, raw_body='{"error": "model not found"}')
        self.addCleanup(fake.close)
        response = OpenAICompatBackend("local-m", fake.base_url, "nope").run("t1", "p")
        self.assertFalse(response.ok)
        self.assertIn("HTTP 404", response.error)
        self.assertIn("model not found", response.error)

    def test_unexpected_body(self):
        fake = _FakeOpenAIServer(raw_body='{"foo": 1}')
        self.addCleanup(fake.close)
        response = OpenAICompatBackend("local-m", fake.base_url, "m").run("t1", "p")
        self.assertFalse(response.ok)
        self.assertIn("형식", response.error)

    def test_connection_refused(self):
        fake = _FakeOpenAIServer()
        url = fake.base_url
        fake.close()
        response = OpenAICompatBackend("local-m", url, "m").run("t1", "p")
        self.assertFalse(response.ok)
        self.assertIn("연결 실패", response.error)


class CheckModelTest(unittest.TestCase):
    def _check(self, model, models):
        fake = _FakeOpenAIServer(models=models)
        self.addCleanup(fake.close)
        return OpenAICompatBackend("local-x", fake.base_url, model).check_model()

    def test_exact_and_latest_tag_match(self):
        self.assertIsNone(self._check("ornith15-9b", ["ornith15-9b:latest"]))
        self.assertIsNone(self._check("qwen3:8b", ["qwen3:8b"]))
        self.assertIsNone(self._check("m:latest", ["m"]))

    def test_missing_model_lists_available(self):
        # 실제 사례: 별칭을 만들지 않고 --models local:ornith15-9b 로 실행
        problem = self._check("ornith15-9b", ["hf.co/bartowski/Ornith-1.5-9B-GGUF:Q4_K_M"])
        self.assertIn("'ornith15-9b'", problem)
        self.assertIn("hf.co/bartowski/Ornith-1.5-9B-GGUF:Q4_K_M", problem)

    def test_runtime_without_models_endpoint_is_skipped(self):
        self.assertIsNone(self._check("m", None))

    def test_connection_refused(self):
        fake = _FakeOpenAIServer()
        url = fake.base_url
        fake.close()
        self.assertIn("연결 실패", OpenAICompatBackend("local-x", url, "m").check_model())


class BuildBackendsTest(unittest.TestCase):
    def test_mixed_specs(self):
        backends = build_backends(["claude", "local:qwen3:8b", "local:ornith-9b"], "http://x/v1")
        self.assertIsInstance(backends[0], CLIBackend)
        self.assertEqual(backends[1].model, "qwen3:8b")
        self.assertEqual(backends[1].name, "local-qwen3_8b")  # 파일명용으로 ':' 치환
        self.assertEqual(backends[2].name, "local-ornith-9b")

    def test_unknown_spec(self):
        with self.assertRaises(ValueError):
            build_backends(["gpt"], "http://x/v1")
        with self.assertRaises(ValueError):
            build_backends(["local:"], "http://x/v1")

    def test_duplicate_spec(self):
        with self.assertRaises(ValueError):
            build_backends(["local:m", "local:m"], "http://x/v1")


if __name__ == "__main__":
    unittest.main()
