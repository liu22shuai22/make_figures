import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import api
import auth
import llm_providers as providers
import token_usage
import request_limits
from request_limits import BusyError, admit
from request_scope import RequestScope, current_scope
from model_transport import NoRedirect, validate_endpoint
from er_generator import llm_settings, LLMConfigurationError


def store(secret, name="own"):
    return {"active_id": name, "providers": [{"id": name, "name": name, "kind": "openai",
            "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "api_key": secret}]}


def header(token, config=None):
    headers = {"Authorization": "Bearer " + token}
    if config is not None:
        headers["X-ERFlow-Providers"] = base64.b64encode(json.dumps(config).encode()).decode()
    return headers


class MultiuserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [patch.object(auth, "DB_PATH", root / "auth.sqlite3"),
                        patch.object(token_usage, "DB_PATH", root / "usage.sqlite3"),
                        patch.object(request_limits, "DB_PATH", root / "limits.sqlite3")]
        for change in self.patches:
            change.start()
        auth._init_table()
        self.a = auth.open_session("alice")
        self.b = auth.open_session("bob")
        self.client = TestClient(api.app)

    def tearDown(self):
        self.client.close()
        for change in reversed(self.patches):
            change.stop()
        self.temp.cleanup()

    def test_browser_channels_do_not_read_or_write_server_credentials(self):
        original = providers.CONFIG_PATH.read_bytes() if providers.CONFIG_PATH.exists() else None
        a = self.client.get("/api/providers/export?secrets=true", headers=header(self.a, store("alpha")))
        b = self.client.get("/api/providers/export?secrets=true", headers=header(self.b, store("beta")))
        self.assertEqual(a.json()["providers"][0]["api_key"], "alpha")
        self.assertEqual(b.json()["providers"][0]["api_key"], "beta")
        self.assertEqual(self.client.get("/api/providers", headers=header(self.a)).json()["providers"], [])
        saved = self.client.post("/api/providers", headers=header(self.a, store("alpha")),
                                 json={"name": "second", "base_url": "https://api.deepseek.com/v1",
                                       "api_key": "new", "model": "deepseek-chat"})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(len(saved.json()["browser_store"]["providers"]), 2)
        self.assertEqual(original, providers.CONFIG_PATH.read_bytes() if original is not None else None)
        self.assertEqual(self.client.get("/api/providers").status_code, 401)
        self.assertEqual(self.client.get("/api/usage").status_code, 401)
        self.assertEqual(self.client.put("/api/providers/active", headers=header(self.b),
                                        json={"id": "own"}).status_code, 404)

    def test_concurrent_contexts_never_change_process_credentials(self):
        before = {name: os.environ.get(name) for name in providers.LLM_ENV_KEYS}
        def resolve(i):
            config = store("key" + str(i))
            config["providers"][0]["base_url"] = "https://1.1.1.1/v1"
            marker = current_scope.set(RequestScope("u" + str(i), config))
            try:
                providers.apply_active_to_environ()
                return llm_settings()[2]
            finally:
                current_scope.reset(marker)
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(list(pool.map(resolve, range(20))), ["key" + str(i) for i in range(20)])
        self.assertEqual(before, {name: os.environ.get(name) for name in providers.LLM_ENV_KEYS})
        marker = current_scope.set(RequestScope("empty"))
        try:
            with self.assertRaises(LLMConfigurationError):
                llm_settings()
        finally:
            current_scope.reset(marker)

    def test_usage_is_owned_by_authenticated_user(self):
        marker = current_scope.set(RequestScope("alice", store("alpha")))
        try:
            token_usage.record_usage({"model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1",
                                      "prompt_tokens": 13, "completion_tokens": 7})
        finally:
            current_scope.reset(marker)
        a = self.client.get("/api/usage", headers=header(self.a))
        b = self.client.get("/api/usage", headers=header(self.b))
        self.assertEqual(a.status_code, 200)
        self.assertEqual(a.json()["total"]["calls"], 1)
        self.assertEqual(b.json()["total"]["calls"], 0)

    def test_internal_endpoints_and_redirects_are_blocked(self):
        for url in ("http://api.deepseek.com/v1", "https://127.0.0.1/v1", "https://[::1]/",
                    "https://169.254.169.254/", "https://10.0.0.1/", "https://user:pass@example.com"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_endpoint(url)
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as caught:
            NoRedirect().redirect_request(type("Req", (), {"full_url": "https://example.com"})(),
                                          None, 302, "", {}, "https://127.0.0.1/")
        caught.exception.close()
        response = self.client.post("/api/providers/list-models", headers=header(self.a),
                                    json={"base_url": "https://127.0.0.1/v1", "api_key": "test"})
        self.assertEqual(response.status_code, 502)

    def test_admission_releases_failures_and_enforces_shared_capacity(self):
        with admit("alice", "render"):
            with self.assertRaises(BusyError):
                with admit("alice", "render"):
                    pass
            with patch.dict(os.environ, {"ERFLOW_RENDER_CONCURRENCY": "1"}):
                with self.assertRaises(BusyError):
                    with admit("bob", "render"):
                        pass
        with self.assertRaises(RuntimeError):
            with admit("alice", "render"):
                raise RuntimeError("failed task")
        with admit("alice", "render"):
            pass

    def test_request_size_and_malformed_credentials_fail_closed(self):
        response = self.client.post("/api/providers", headers=header(self.a),
                                    content=b"x" * (256 * 1024 + 1))
        self.assertEqual(response.status_code, 413)
        headers = header(self.a)
        headers["X-ERFlow-Providers"] = "invalid-base64"
        self.assertEqual(self.client.get("/api/providers", headers=headers).status_code, 422)


if __name__ == "__main__":
    unittest.main()
