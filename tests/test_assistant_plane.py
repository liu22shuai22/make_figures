import unittest
from unittest.mock import patch

from assistant import run_turn
from assistant.knowledge import lookup_faq
from assistant.memory import last_topic, looks_like_follow_up, resolve_lookup_query
from assistant.router import can_model_route, parse_route_payload, route, rule_route, try_model_route
from assistant.types import TurnContext


class AssistantPlaneTests(unittest.TestCase):
    def test_combined_requests_go_through_each_tool_policy(self):
        result = run_turn("检查模型，然后帮我改基数", surface="workbench")
        tools = [s for s in result.trace["steps"] if s["stage"] == "tool"]
        self.assertEqual([(s["name"], s["status"]) for s in tools],
                         [("draft.open_review", "ok"), ("draft.propose_cardinality", "auth")])
        self.assertTrue(result.trace["combined"])
        self.assertEqual(result.trace["tools"], ["draft.open_review", "draft.propose_cardinality"])
        self.assertEqual(result.actions, [{"type": "open_review"}])
        self.assertIsNone(result.cardinality)
        self.assertEqual(run_turn("帮我改基数", surface="workbench", authenticated=True,
                                  diagram_kind="usecase").trace["blocked"], "diagram_kind")
        refused = run_turn("怎么开始？顺便查看Token用量和赌博")
        self.assertEqual([s["stage"] for s in refused.trace["steps"]], ["policy"])
        # Encyclopedic / paid lookups stay single-turn even with connectors.
        wiki_combo = run_turn("怎么开始？顺便你知道APEC吗", surface="welcome")
        self.assertFalse(wiki_combo.trace.get("combined"))
        self.assertEqual(wiki_combo.trace.get("tools"), ["faq.answer"])

    def test_history_is_scoped_and_replay_does_not_execute(self):
        import tempfile
        from pathlib import Path
        from fastapi.testclient import TestClient
        import api
        import auth
        from assistant import trace_store

        with tempfile.TemporaryDirectory() as tmp, patch.object(auth, "DB_PATH", Path(tmp) / "auth.db"), \
                patch.object(trace_store, "DB_PATH", Path(tmp) / "trace.db"), TestClient(api.app) as client:
            auth._init_table()
            alice = {"Authorization": "Bearer " + auth.open_session("alice")}
            bob = {"Authorization": "Bearer " + auth.open_session("bob")}
            response = client.post("/api/assistant/turn", headers=alice, json={"message": "怎么开始？顺便查看Token用量"})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual([m["trace"]["tool"] for m in data["messages"]], ["faq.answer", "usage.explain"])
            self.assertEqual(data["actions"], [{"type": "show_usage"}])
            path = "/api/assistant/traces"
            self.assertEqual(client.get(path).status_code, 401)
            self.assertEqual(client.get(path, headers=bob).json()["turns"], [])
            self.assertEqual(client.get(path, headers=alice).json()["turns"][0]["steps"], data["trace"]["steps"])
            for _ in range(trace_store.KEEP):
                trace_store.save("alice", [])
            self.assertEqual(len(trace_store.recent("alice")), trace_store.KEEP)
            self.assertTrue(all(not row["steps"] for row in trace_store.recent("alice")))

    def test_workbench_encyclopedia_question_does_not_fall_into_edit(self):
        ctx = TurnContext(message="你知道APEC吗", surface="workbench",
                          spec={"relations": [{"entities": ["A", "B"]}]})
        self.assertEqual(rule_route(ctx).tool, "web.lookup")

    def test_legacy_and_current_binary_drafts(self):
        from assistant.policy import has_binary_relation
        for relation in ({"a": "学生", "b": "课程"}, {"entities": ["学生", "课程"]}):
            self.assertTrue(has_binary_relation({"relations": [relation]}))
        self.assertFalse(has_binary_relation({"relations": [{"a": "学生", "b": "课程", "c": "教师"}]}))

    def test_faq_hit_is_local_band(self):
        result = run_turn("怎么开始？", surface="welcome", locale="zh")
        self.assertEqual(result.band, "local_faq")
        self.assertTrue(result.messages)
        self.assertIn("三步", result.messages[0].text)

    def test_off_topic_is_refuse_not_fake_fallback(self):
        result = run_turn("你知道习近平吗", surface="welcome", locale="zh")
        self.assertEqual(result.band, "refuse")
        self.assertIn("能力范围", result.messages[0].text)

    def test_model_identity_explains_channel(self):
        fake = {
            "id": "1",
            "name": "DeepSeek",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "x",
            "kind": "openai",
        }
        with patch("llm_providers.active_provider", return_value=fake):
            result = run_turn("你是什么模型", surface="welcome", locale="zh")
        self.assertEqual(result.band, "local_faq")
        self.assertIn("deepseek-chat", result.messages[0].text)

    def test_check_intent_opens_review_on_workbench(self):
        result = run_turn("检查模型", surface="workbench", locale="zh")
        self.assertEqual(result.band, "open_review")
        self.assertTrue(any(item.get("type") == "open_review" for item in result.actions))

    def test_cardinality_requires_auth_on_workbench(self):
        spec = {
            "title": "选课",
            "entities": [{"name": "学生"}, {"name": "课程"}],
            "relations": [{"name": "选修", "entities": ["学生", "课程"], "card": ["n", "n"], "attrs": []}],
        }
        result = run_turn(
            "限制每个学生最多选一门课",
            surface="workbench",
            locale="zh",
            spec=spec,
            authenticated=False,
        )
        self.assertEqual(result.band, "product_tool")
        self.assertIn("登录", result.messages[0].text)

    def test_router_knowledge_vs_refuse(self):
        hit = rule_route(TurnContext(message="导出会糊吗", locale="zh"))
        self.assertEqual(hit.tool, "faq.answer")
        miss = rule_route(TurnContext(message="今天天气怎么样", locale="zh"))
        self.assertEqual(miss.band, "refuse")
        self.assertIsNotNone(lookup_faq("什么是语义沙", "zh"))

    def test_parse_route_payload_accepts_whitelist_only(self):
        ok = parse_route_payload({"band": "refuse", "tool": "scope.refuse", "reason": "chat"})
        self.assertEqual(ok.band, "refuse")
        web = parse_route_payload({"band": "web_search", "tool": "web.lookup", "reason": "apec"})
        self.assertEqual(web.tool, "web.lookup")
        self.assertIsNone(parse_route_payload({"band": "web_search", "tool": "web.search", "reason": "x"}))
        self.assertIsNone(parse_route_payload({"band": "local_faq", "tool": "scope.refuse", "reason": "bad"}))

    def test_lookup_pattern_routes_to_web_search(self):
        plan = rule_route(TurnContext(message="你知道APEC吗", locale="zh"))
        self.assertEqual(plan.band, "web_search")
        self.assertEqual(plan.tool, "web.lookup")

    def test_web_lookup_extracts_query(self):
        from assistant.tools.web_lookup import extract_lookup_query

        self.assertEqual(extract_lookup_query("你知道APEC吗"), "APEC")
        self.assertEqual(extract_lookup_query("什么是 UML"), "UML")

    def test_web_lookup_prefers_defined_acronym_over_compound_title(self):
        from assistant.tools.web_lookup import _summary_score, _title_score

        youth = _title_score("APEC", "APEC 青年科學節")
        org = _summary_score(
            "APEC",
            {
                "title": "亚太经济合作组织",
                "extract": "亚太经济合作组织（APEC）是亚太地区的经济合作论坛。",
            },
        )
        en = _summary_score(
            "APEC",
            {
                "title": "Asia-Pacific Economic Cooperation",
                "extract": "Asia-Pacific Economic Cooperation (APEC) is a forum.",
            },
        )
        summit = _title_score("APEC", "2026年中国APEC峰会")
        self.assertGreater(org, youth)
        self.assertGreater(en, youth)
        self.assertGreater(org, summit)
        self.assertLess(
            _summary_score("APEC", {"title": "APEC 青年科學節", "extract": "science fair"}),
            0,
        )
        self.assertGreaterEqual(org, 20)
        self.assertGreaterEqual(en, 20)

    def test_web_lookup_falls_back_to_model_when_wiki_fails(self):
        with patch("assistant.router.can_model_route", return_value=False):
            with patch("assistant.tools.web_lookup._wikipedia_summary", side_effect=TimeoutError("slow")):
                with patch(
                    "assistant.tools.web_lookup._model_brief_answer",
                    return_value="APEC 是亚太经合组织。",
                ):
                    result = run_turn(
                        "你知道APEC吗",
                        surface="welcome",
                        locale="zh",
                        authenticated=True,
                    )
        self.assertEqual(result.band, "web_search")
        self.assertIn("亚太经合组织", result.messages[0].text)
        self.assertEqual(result.trace.get("fallback"), "model_brief")

    def test_follow_up_uses_history_topic(self):
        history = [
            {"role": "user", "text": "你知道APEC吗"},
            {
                "role": "bot",
                "text": "「亚太经济合作组织」\n简介",
                "band": "web_search",
                "topic": "亚太经济合作组织",
            },
        ]
        ctx = TurnContext(message="它有哪些成员", locale="zh", history=history)
        self.assertEqual(last_topic(ctx), "亚太经济合作组织")
        self.assertTrue(looks_like_follow_up("它有哪些成员"))
        query, topic = resolve_lookup_query(ctx, "")
        self.assertIn("亚太经济合作组织", query)
        self.assertEqual(topic, "亚太经济合作组织")
        with patch("assistant.router.can_model_route", return_value=False):
            plan = rule_route(ctx)
        self.assertEqual(plan.tool, "web.lookup")
        self.assertEqual(plan.reason, "follow_up_topic")

    def test_model_router_used_when_eligible_and_falls_back_on_failure(self):
        fake = {
            "id": "1",
            "name": "DeepSeek",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "x",
            "kind": "openai",
        }
        ctx = TurnContext(message="导出会糊吗", locale="zh", authenticated=True)
        self.assertFalse(can_model_route(TurnContext(message="hi", authenticated=False)))
        with patch("llm_providers.active_provider", return_value=fake):
            self.assertTrue(can_model_route(ctx))
            with patch("assistant.router._call_router_model", return_value={
                "band": "local_faq", "tool": "faq.answer", "reason": "export",
            }):
                plan = route(ctx)
            self.assertEqual(plan.tool, "faq.answer")
            self.assertTrue(plan.reason.startswith("model"))
            with patch("assistant.router._call_router_model", side_effect=RuntimeError("boom")):
                fallback = try_model_route(ctx)
            self.assertIsNone(fallback)
            with patch("assistant.router._call_router_model", side_effect=RuntimeError("boom")):
                plan2 = route(ctx)
            self.assertEqual(plan2.tool, "faq.answer")
            self.assertEqual(plan2.reason, "knowledge_hit")


if __name__ == "__main__":
    unittest.main()
