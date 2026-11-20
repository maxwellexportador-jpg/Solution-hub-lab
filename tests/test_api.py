import json
import socket
import unittest
import urllib.error
import urllib.request

from solution_print.api import LabServer, ServerConfig

TOKEN = "token-de-teste-local"


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = LabServer(config=ServerConfig(host="127.0.0.1", port=0, token=TOKEN))
        cls.server.build()
        cls.port = cls.server.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()

    def call(self, path, method="GET", payload=None, token=TOKEN, raw=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = raw if raw is not None else (
            json.dumps(payload).encode("utf-8") if payload is not None else None
        )
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer %s" % token
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read()
                return response.status, json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    # ------------------------------------------------------------------ #
    def test_health(self) -> None:
        status, body = self.call("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["contract_version"], "1.0")
        self.assertGreater(body["models"]["known"], 0)
        self.assertEqual(body["upstream"]["project"], "jingyaogong/minimind")

    def test_models_endpoint_marks_simulated_models(self) -> None:
        status, body = self.call("/v1/models")
        self.assertEqual(status, 200)
        self.assertEqual(body["object"], "list")
        echo = next(item for item in body["data"] if item["id"] == "sp-echo-baseline-v1")
        self.assertTrue(echo["simulated"])
        self.assertEqual(echo["cost"], "free")

    def test_requires_token(self) -> None:
        status, body = self.call("/health", token=None)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "unauthorized")
        status, _ = self.call("/health", token="errado")
        self.assertEqual(status, 401)

    def test_chat_completion_with_fixture(self) -> None:
        status, body = self.call(
            "/v1/chat/completions",
            method="POST",
            payload={"messages": [{"role": "user", "content": "Explique impressão 3D."}]},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["simulated"])
        self.assertEqual(body["object"], "chat.completion")
        self.assertTrue(body["choices"][0]["message"]["content"])
        self.assertIn("trace_id", body["solution_print"])

    def test_unknown_model_returns_404(self) -> None:
        status, body = self.call(
            "/v1/chat/completions",
            method="POST",
            payload={"model": "nao-existe", "messages": [{"role": "user", "content": "oi"}]},
        )
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "ModelNotFound")

    def test_invalid_json_returns_400(self) -> None:
        status, body = self.call(
            "/v1/chat/completions", method="POST", raw=b"{isto nao e json"
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_json")

    def test_missing_messages_returns_400(self) -> None:
        status, body = self.call("/v1/chat/completions", method="POST", payload={"model": "x"})
        self.assertEqual(status, 400)
        self.assertIn("messages", body["error"]["message"])

    def test_invalid_role_returns_400(self) -> None:
        status, body = self.call(
            "/v1/chat/completions",
            method="POST",
            payload={"messages": [{"role": "root", "content": "oi"}]},
        )
        self.assertEqual(status, 400)
        self.assertIn("role", body["error"]["message"])

    def test_secret_in_prompt_is_blocked(self) -> None:
        status, body = self.call(
            "/v1/chat/completions",
            method="POST",
            payload={
                "messages": [
                    {"role": "user", "content": "minha chave é sk-" + "a" * 24}
                ]
            },
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "PolicyViolation")
        self.assertNotIn("sk-", body["error"]["message"])

    def test_route_endpoint(self) -> None:
        status, body = self.call("/v1/lab/route?task=ptbr")
        self.assertEqual(status, 200)
        self.assertIn("model_id", body)
        self.assertIn("reasons", body)

    def test_unknown_endpoint_returns_404(self) -> None:
        status, body = self.call("/v1/nada")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "not_found")

    def test_body_limit_rejects_oversized_payload(self) -> None:
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as connection:
            connection.sendall(
                (
                    "POST /v1/chat/completions HTTP/1.1\r\n"
                    "Host: 127.0.0.1\r\n"
                    "Authorization: Bearer %s\r\n"
                    "Content-Type: application/json\r\n"
                    "Content-Length: 200000\r\n"
                    "Connection: close\r\n\r\n" % TOKEN
                ).encode("ascii")
            )
            raw = b""
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                raw += chunk
        self.assertIn(b"413", raw.split(b"\r\n", 1)[0])


if __name__ == "__main__":
    unittest.main()
