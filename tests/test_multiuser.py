import base64
import asyncio
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import sqlite3
import subprocess
import sys
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
            with patch.object(request_limits, "RENDER_CAPACITY", 1):
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

    def test_validation_does_not_echo_secrets_and_errors_cannot_be_cached(self):
        secret = "sensitive-do-not-echo"
        response = self.client.post("/api/providers", headers=header(self.a),
                                    json={"name": "test", "api_key": {"secret": secret}})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(secret, response.text)
        self.assertTrue(all("input" not in item for item in response.json()["detail"]))
        for response in (response, self.client.get("/api/providers", headers={"X-ERFlow-Providers": "bad"}),
                         self.client.post("/api/providers", content=b"x" * (256 * 1024 + 1))):
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_local_review_and_faq_work_while_account_model_is_busy(self):
        with admit("account:alice", "model"):
            response = self.client.post("/api/assistant/turn", headers=header(self.a, store("unused")),
                                        json={"message": "怎么开始？", "surface": "workbench", "locale": "zh"})
            self.assertEqual(response.status_code, 200, response.text)
            response = self.client.post("/api/assistant/review", headers=header(self.a),
                                        json={"spec": {"entities": [{"name": "学生", "attrs": ["*编号"]}], "relations": []}})
            self.assertEqual(response.status_code, 200, response.text)

    def test_actual_model_admission_blocks_before_outbound_and_cleans_up(self):
        from er_generator import llm_chat
        marker = current_scope.set(RequestScope("alice", store("unused")))
        try:
            with admit("account:alice", "model"):
                with self.assertRaises(BusyError):
                    llm_chat([], "openai", "unused", "unused", "https://127.0.0.1")
        finally:
            current_scope.reset(marker)
        with admit("account:alice", "model"):
            pass

    def test_render_semaphore_busy_returns_429(self):
        slots = []
        try:
            while api.render_slot.acquire(blocking=False):
                slots.append(True)
            response = self.client.post("/api/render", headers=header(self.a), json={})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers["retry-after"], "5")
        finally:
            for _ in slots:
                api.render_slot.release()

    def test_busy_soft_router_falls_back_without_model_request(self):
        config = store("unused")
        config["providers"][0]["base_url"] = "https://1.1.1.1/v1"
        with admit("account:alice", "model"):
            response = self.client.post("/api/assistant/turn", headers=header(self.a, config),
                                        json={"message": "你好呀", "surface": "workbench"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["messages"])

    def test_busy_continue_preserves_completed_messages_and_actions(self):
        config = store("unused")
        config["providers"][0]["base_url"] = "https://1.1.1.1/v1"
        with admit("account:alice", "model"):
            response = self.client.post("/api/assistant/turn", headers=header(self.a, config),
                                        json={"message": "检查模型", "surface": "workbench"})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(any("检查模型" in item["text"] for item in data["messages"]))
        self.assertIn({"type": "open_review"}, data["actions"])
        self.assertEqual(data["trace"]["tools"], ["draft.open_review"])

    def test_explicit_model_tool_still_returns_429_when_busy(self):
        config = store("unused")
        config["providers"][0]["base_url"] = "https://1.1.1.1/v1"
        spec = {"entities": [{"name": "学生", "attrs": ["*编号"]},
                             {"name": "课程", "attrs": ["*编号"]}],
                "relations": [{"name": "选修", "a": "学生", "b": "课程", "card": ["m", "n"]}]}
        with admit("account:alice", "model"):
            response = self.client.post("/api/assistant/turn", headers=header(self.a, config),
                                        json={"message": "改成每个学生只能选一门课程", "surface": "workbench", "spec": spec})
        self.assertEqual(response.status_code, 429, response.text)
        self.assertEqual(response.headers["retry-after"], "5")

    def test_web_lookup_model_brief_busy_soft_fails(self):
        config = store("unused")
        config["providers"][0]["base_url"] = "https://1.1.1.1/v1"
        with patch("assistant.tools.web_lookup._wikipedia_summary", return_value=None):
            with admit("account:alice", "model"):
                response = self.client.post(
                    "/api/assistant/turn",
                    headers=header(self.a, config),
                    json={"message": "什么是 UML", "surface": "workbench", "locale": "zh"},
                )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["messages"])
        self.assertIn("web.lookup", data["trace"]["tools"])
        self.assertFalse(data["trace"].get("hit"))

    def test_auth_limit_cannot_be_reset_by_switching_accounts(self):
        for i in range(10):
            response = self.client.post("/api/auth/login", headers=header(self.a if i % 2 else self.b), json={})
            self.assertEqual(response.status_code, 422)
        response = self.client.post("/api/auth/login", json={})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "5")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_separate_process_observes_busy_slot(self):
        code = '''
import sys
from pathlib import Path
import request_limits
request_limits.DB_PATH = Path(sys.argv[1])
request_limits.RENDER_CAPACITY = 1
try:
    with request_limits.admit("other-process", "render"):
        raise SystemExit(2)
except request_limits.BusyError:
    print("busy")
'''
        with patch.object(request_limits, "RENDER_CAPACITY", 1):
            with admit("parent", "render"):
                result = subprocess.run([sys.executable, "-c", code, str(request_limits.DB_PATH)],
                                         capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "busy")

    def test_sqlite_contention_does_not_block_unrelated_async_requests(self):
        import httpx
        # Real SQLite writer lock; no simulated API or substituted limiter.
        with admit("initialize", "render"):
            pass
        async def check():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
                with closing(sqlite3.connect(request_limits.DB_PATH)) as locked:
                    locked.execute("BEGIN IMMEDIATE")
                    pending = asyncio.create_task(client.post("/api/auth/login", json={}))
                    try:
                        await asyncio.sleep(0.1)
                        start = asyncio.get_running_loop().time()
                        response = await client.get("/api/providers")
                        self.assertEqual(response.status_code, 401)
                        self.assertLess(asyncio.get_running_loop().time() - start, 1)
                        self.assertFalse(pending.done())
                    finally:
                        locked.rollback()
                        result = await pending
                    self.assertEqual(result.status_code, 422)
        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
