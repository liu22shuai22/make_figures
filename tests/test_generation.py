from http.client import RemoteDisconnected
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from api import GenerateRequest, generate, get_usage, validate_web_spec
from er_generator import normalize_spec


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "examples" / "course-selection.json"
MODEL_ENV = {"LLM_API_KEY": "test-key", "LLM_MODEL": "test-model", "LLM_BASE_URL": "https://provider.example/v1"}
SILICONFLOW_ENV = {**MODEL_ENV, "LLM_BASE_URL": "https://api.siliconflow.cn/v1/",
                   "LLM_MODEL": "deepseek-ai/DeepSeek-V4.1-Flash"}


def model_reply(text, usage=None):
    return BytesIO(json.dumps({"choices": [{"message": {"content": text}}], "usage": usage}).encode("utf-8"))


def stream_reply(*chunks, complete=True, done=True, usage=None):
    events = [{"choices": [{"delta": {"reasoning_content": "ignore"}}]}]
    events.extend({"choices": [{"delta": {"content": chunk}}]} for chunk in chunks)
    if complete:
        events.extend(({"choices": [{"delta": {}, "finish_reason": "stop"}]}, {"choices": [], "usage": usage or {}}))
    body = b": keepalive\r\n\r\n"
    body += b"".join(b"data: " + json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\r\n\r\n"
                     for event in events)
    if complete and done:
        body += b"data: [DONE]\r\n\r\n"
    response = BytesIO(body)
    response.headers = {"Content-Type": "text/event-stream; charset=utf-8"}
    return response


class GenerateTests(unittest.TestCase):
    def setUp(self):
        db_path = Path(__file__).with_name(f".test-usage-{uuid4().hex}.sqlite3")
        self.addCleanup(db_path.unlink, missing_ok=True)
        self.enterContext(patch("token_usage.DB_PATH", db_path))

    def test_usage_counts_disconnected_and_reported_calls_separately(self):
        raw = SAMPLE_PATH.read_text(encoding="utf-8")
        self.assertEqual(get_usage()["daily"], [])
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen",
            side_effect=[RemoteDisconnected(), model_reply(
                raw, usage={"prompt_tokens": 105, "completion_tokens": 37}
            )],
        ):
            generate(GenerateRequest(text="学生选课，记录成绩"))

        usage = get_usage()
        self.assertEqual(usage["total"], {
            "input_tokens": 105, "output_tokens": 37, "calls": 2, "unreported_calls": 1,
        })
        self.assertEqual(usage["daily"], [usage["today"]])

    def test_web_spec_accepts_twenty_four_entities_and_forty_relations(self):
        names = [f"模块{i}" for i in range(25)]
        entities = [{"name": name} for name in names[:24]]
        relations = [{"name": f"联系{i}", "a": names[i % 24], "b": names[(i + 1) % 24]}
                     for i in range(41)]
        validate_web_spec(normalize_spec({"entities": entities, "relations": relations[:40]}))
        for extra_entities, extra_relations in ((1, 0), (0, 1)):
            with self.subTest(entities=24 + extra_entities, relations=40 + extra_relations):
                with self.assertRaisesRegex(ValueError, "24 个实体和 40 条联系"):
                    validate_web_spec(normalize_spec({
                        "entities": entities + [{"name": names[-1]}] * extra_entities,
                        "relations": relations[:40 + extra_relations],
                    }))

    def test_accepts_twenty_one_entities_without_requesting_a_correction(self):
        names = [f"业务模块{i}" for i in range(21)]
        raw = {"entities": [{"name": name} for name in names],
               "relations": [{"name": f"联系{i}", "a": names[i % 21], "b": names[(i + 1) % 21]}
                             for i in range(27)]}
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", return_value=model_reply(json.dumps(raw))
        ) as http:
            spec = generate(GenerateRequest(text="设计业务管理系统"))["spec"]

        http.assert_called_once()
        self.assertEqual([entity["name"] for entity in spec["entities"]], names)
        self.assertEqual(len(spec["relations"]), 27)

    def test_repairs_generated_isolated_entity_without_replacing_existing_spec(self):
        raw = {"title": "优惠券管理", "entities": [{"name": name} for name in ("消费者", "优惠券", "领券记录")],
               "relations": [{"name": "领取", "a": "消费者", "b": "优惠券", "attrs": ["领取时间"]}]}
        repair = {"relations": [{"name": "生成", "a": "消费者", "b": "领券记录"},
                                {"name": "对应", "a": "优惠券", "b": "领券记录"}]}
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=[stream_reply(json.dumps(raw)),
                stream_reply(json.dumps(repair), complete=False)]
        ) as http:
            spec = generate(GenerateRequest(text="消费者领取优惠券，需保留领券记录"))["spec"]

        self.assertEqual(http.call_count, 2)
        self.assertIn("领券记录", json.loads(http.call_args.args[0].data)["messages"][-1]["content"])
        self.assertEqual([entity["name"] for entity in spec["entities"]], ["消费者", "优惠券", "领券记录"])
        self.assertEqual(spec["relations"][0]["attrs"], ["领取时间"])
        self.assertEqual([relation["entities"] for relation in spec["relations"][1:]],
                         [["消费者", "领券记录"], ["优惠券", "领券记录"]])

    def test_repair_cannot_add_unrelated_links_or_drop_isolated_entity(self):
        raw = {"entities": [{"name": name} for name in ("消费者", "优惠券", "领券记录")],
               "relations": [{"name": "领取", "a": "消费者", "b": "优惠券"}]}
        unrelated = {"relations": [{"name": "使用", "a": "消费者", "b": "优惠券"}]}
        with patch.dict("os.environ", MODEL_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=[model_reply(json.dumps(raw)),
                model_reply(json.dumps(unrelated))]
        ), self.assertRaises(HTTPException) as caught:
            generate(GenerateRequest(text="优惠券业务"))

        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("领券记录", caught.exception.detail)
        self.assertIn("新增联系须涉及", caught.exception.detail)

    def test_interrupted_relation_repair_preserves_complete_records_and_targets_missing_entity(self):
        raw = {"entities": [{"name": name} for name in ("员工", "文档", "评论", "点赞")],
               "relations": [{"name": "编辑", "a": "员工", "b": "文档"}]}
        partial = '{"relations":[{"name":"收到评论","a":"文档","b":"评论"},{"name":'
        final = {"relations": [{"name": "获赞", "a": "文档", "b": "点赞"}]}
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=[stream_reply(json.dumps(raw)),
                stream_reply(partial, complete=False), model_reply(json.dumps(final))]
        ) as http:
            spec = generate(GenerateRequest(text="员工编辑文档，文档可被评论和点赞"))["spec"]

        self.assertEqual(http.call_count, 3)
        body = json.loads(http.call_args.args[0].data)
        self.assertFalse(body["stream"])
        context = json.loads(body["messages"][-1]["content"])
        self.assertEqual(context["待连接实体"], "点赞")
        self.assertEqual([item["name"] for item in context["当前规格"]["relations"]], ["编辑", "收到评论"])
        self.assertEqual([item["name"] for item in spec["relations"]], ["编辑", "收到评论", "获赞"])

    def test_repairs_an_entity_that_only_has_a_self_relation(self):
        raw = {"entities": [{"name": name} for name in ("员工", "文档", "评论")],
               "relations": [{"name": "编辑", "a": "员工", "b": "文档"},
                             {"name": "回复", "a": "评论", "b": "评论"}]}
        repair = {"relations": [{"name": "收到评论", "a": "文档", "b": "评论"}]}
        with patch.dict("os.environ", MODEL_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen",
            side_effect=[model_reply(json.dumps(raw)), model_reply(json.dumps(repair))]
        ) as http:
            spec = generate(GenerateRequest(text="员工编辑文档，文档有评论，评论可互相回复"))["spec"]

        self.assertEqual(http.call_count, 2)
        self.assertEqual([item["entities"] for item in spec["relations"]],
                         [["员工", "文档"], ["评论", "评论"], ["文档", "评论"]])

    def test_retries_when_model_spec_cannot_be_rendered(self):
        raw = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        raw["relations"][0]["card"] = ["invalid", "n"]
        invalid = model_reply(json.dumps(raw))
        raw["relations"][0]["card"] = ["m", "n"]
        corrected = model_reply("```json\n" + json.dumps(raw, ensure_ascii=False) + "\n```")

        with patch.dict("os.environ", MODEL_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=[invalid, corrected]
        ) as http:
            spec = generate(GenerateRequest(text="  学生选修课程，记录成绩。  "))["spec"]

        self.assertEqual(http.call_count, 2)
        request = http.call_args.args[0]
        messages = json.loads(request.data)["messages"]
        self.assertIn("学生选修课程，记录成绩。", messages[1]["content"])
        self.assertIn("基数", messages[-1]["content"])
        self.assertEqual(request.full_url, "https://provider.example/v1/chat/completions")
        self.assertNotIn("enable_thinking", json.loads(request.data))
        self.assertEqual(http.call_args.kwargs["timeout"], 90)
        model = normalize_spec(spec)
        validate_web_spec(model)
        self.assertEqual(spec["relations"][0]["entities"], ["学生", "课程"])
        self.assertEqual(spec["relations"][0]["attrs"], ["成绩"])

    def test_anthropic_response_preserves_ternary_and_self_relations(self):
        raw = {
            "entities": [{"name": "甲"}, {"name": "乙"}, {"name": "丙"}],
            "relations": [
                {"name": "协作", "entities": ["甲", "乙", "丙"], "card": ["m", "n", "p"]},
                {"name": "管理", "a": "甲", "b": "甲", "card": ["1", "n"]},
            ],
        }
        result = {"content": [{"type": "text", "text": json.dumps(raw)}]}
        env = {"ANTHROPIC_API_KEY": "test-key", "LLM_MODEL": "test-model"}
        with patch.dict("os.environ", env, clear=True), patch(
            "er_generator.urllib.request.urlopen", return_value=BytesIO(json.dumps(result).encode("utf-8"))
        ) as http:
            spec = generate(GenerateRequest(text="设计协作系统"))["spec"]

        self.assertEqual(http.call_args.args[0].full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(spec["relations"][0]["entities"], ["甲", "乙", "丙"])
        self.assertEqual(spec["relations"][1]["entities"], ["甲", "甲"])
        self.assertEqual(spec["entities"][0]["attrs"], [{"name": "甲ID", "pk": True}])

    def test_returns_502_without_exposing_provider_error_body(self):
        error = HTTPError("https://provider.example", 401, "secret header", {}, BytesIO(b"secret body"))
        with patch.dict("os.environ", MODEL_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=error
        ), self.assertRaises(HTTPException) as caught:
            generate(GenerateRequest(text="设计图书系统"))

        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("401", caught.exception.detail)
        self.assertNotIn("secret", caught.exception.detail)

    def test_returns_502_after_one_unsuccessful_correction(self):
        with patch.dict("os.environ", MODEL_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=[model_reply("invalid"), model_reply("invalid")]
        ) as http, self.assertRaises(HTTPException) as caught:
            generate(GenerateRequest(text="设计图书系统"))

        self.assertEqual(http.call_count, 2)
        self.assertEqual(caught.exception.status_code, 502)

    def test_returns_504_for_provider_timeout(self):
        with patch.dict("os.environ", MODEL_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=URLError(TimeoutError())
        ), self.assertRaises(HTTPException) as caught:
            generate(GenerateRequest(text="设计图书系统"))

        self.assertEqual(caught.exception.status_code, 504)
        self.assertIn("90 秒", caught.exception.detail)

    def test_returns_safe_transport_diagnostic(self):
        with patch.dict("os.environ", MODEL_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=RemoteDisconnected("private transport details")
        ) as http, patch("er_generator.time.sleep") as wait, self.assertRaises(HTTPException) as caught:
            generate(GenerateRequest(text="设计图书系统"))

        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("RemoteDisconnected", caught.exception.detail)
        self.assertNotIn("private", caught.exception.detail)
        self.assertEqual(http.call_count, 2)
        wait.assert_called_once_with(1)

    def test_reconnects_once_without_changing_the_prompt(self):
        raw = SAMPLE_PATH.read_text(encoding="utf-8")
        with patch.dict("os.environ", MODEL_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=[RemoteDisconnected(), model_reply(raw)]
        ) as http, patch("er_generator.time.sleep") as wait:
            spec = generate(GenerateRequest(text="学生选课，记录成绩"))["spec"]

        self.assertEqual(spec["relations"][0]["attrs"], ["成绩"])
        self.assertEqual(http.call_count, 2)
        self.assertEqual(http.call_args_list[0].args[0].data, http.call_args_list[1].args[0].data)
        wait.assert_called_once_with(1)

    def test_siliconflow_retry_uses_remaining_budget_and_same_endpoint(self):
        raw = SAMPLE_PATH.read_text(encoding="utf-8")
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=[RemoteDisconnected(), model_reply(raw)]
        ) as http, patch("er_generator.time.monotonic", side_effect=[0, 0, 0, 65, 65, 65]), patch(
            "er_generator.time.sleep"
        ) as wait:
            spec = generate(GenerateRequest(text="学生选课，记录成绩"))["spec"]

        self.assertEqual(spec["relations"][0]["attrs"], ["成绩"])
        self.assertEqual([call.kwargs["timeout"] for call in http.call_args_list], [75, 55])
        first, retry = [call.args[0] for call in http.call_args_list]
        self.assertEqual(first.full_url, "https://api.siliconflow.cn/v1/chat/completions")
        self.assertEqual(retry.full_url, first.full_url)
        first_body, retry_body = json.loads(first.data), json.loads(retry.data)
        self.assertIs(first_body.pop("stream"), True)
        self.assertIs(retry_body.pop("stream"), False)
        self.assertEqual(first_body, retry_body)
        self.assertIs(retry_body["enable_thinking"], False)
        self.assertEqual(retry.get_header("Accept"), "application/json")
        wait.assert_not_called()

    def test_siliconflow_reports_when_both_response_modes_disconnect(self):
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=RemoteDisconnected("private transport details")
        ) as http, self.assertRaises(HTTPException) as caught:
            generate(GenerateRequest(text="学生选课"))

        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual([json.loads(call.args[0].data)["stream"] for call in http.call_args_list], [True, False])
        self.assertIn("流式和非流式请求均未完成", caught.exception.detail)
        self.assertIn("RemoteDisconnected", caught.exception.detail)
        self.assertNotIn("private", caught.exception.detail)

    def test_truncated_siliconflow_stream_is_discarded_before_retry(self):
        raw = SAMPLE_PATH.read_text(encoding="utf-8")
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen",
            side_effect=[stream_reply('{"incomplete":', complete=False), stream_reply(raw[:37], raw[37:])],
        ) as http:
            spec = generate(GenerateRequest(text="学生选课，记录成绩"))["spec"]

        self.assertEqual(http.call_count, 2)
        self.assertEqual(spec["relations"][0]["attrs"], ["成绩"])
        self.assertEqual(http.call_args.args[0].get_header("Accept"), "text/event-stream")

    def test_siliconflow_resumes_from_completed_entities_and_relations(self):
        first = '{"title":"选课","entities":[{"name":"学生","attrs":["*编号","说明{示例}"]}'
        middle = ',{"name":"课程"},{"name":"学院"}],"relations":[{"name":"选修","a":"学生","b":"课程"}'
        last = ',{"name":"开设","a":"学院","b":"课程"}]}'
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=[
                stream_reply(first + ',{"name":"课', complete=False),
                stream_reply(middle + ',{"name":"开', complete=False),
                stream_reply(last, complete=False),
            ],
        ) as http:
            spec = generate(GenerateRequest(text="学生选课，学院开设课程"))["spec"]

        self.assertEqual(http.call_count, 3)
        for call, prefix in zip(http.call_args_list[1:], [first, first + middle]):
            request = call.args[0]
            self.assertEqual(request.full_url, "https://api.siliconflow.cn/v1/chat/completions")
            messages = json.loads(request.data)["messages"]
            context = json.loads(messages[-1]["content"])
            self.assertEqual(context["已完成的 JSON 前缀"], prefix)
            self.assertIn("学生选课，学院开设课程", context["需求对话"][0]["content"])
        self.assertEqual([item["name"] for item in spec["entities"]], ["学生", "课程", "学院"])
        self.assertEqual([item["name"] for item in spec["relations"]], ["选修", "开设"])

    def test_siliconflow_continues_past_five_attempts_after_isolated_stalls(self):
        names = [f"业务模块{i:02d}" for i in range(21)]
        raw = {"title": "业务管理", "entities": [{"name": name, "attrs": ["*编号", "名称", "状态", "日期"]}
                                               for name in names],
               "relations": [{"name": f"业务联系{i}", "a": names[i % 21], "b": names[(i + 1) % 21],
                              "card": ["1", "n"], "attrs": ["办理日期"]} for i in range(27)]}
        payload = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
        prefixes = []

        def open_response(request, timeout):
            attempt = len(prefixes)
            messages = json.loads(request.data)["messages"]
            prefix = json.loads(messages[-1]["content"])["已完成的 JSON 前缀"] if attempt else ""
            self.assertTrue(payload.startswith(prefix))
            prefixes.append(len(prefix))
            if attempt in (1, 4):
                return stream_reply("请重新生成。")
            size = {0: 712, 2: 593, 3: 659}.get(attempt, 666)
            return stream_reply(payload[len(prefix):len(prefix) + size], complete=False)

        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=open_response
        ):
            spec = generate(GenerateRequest(text="设计业务管理系统"))["spec"]

        self.assertGreater(len(prefixes), 6)  # 初次请求加旧版最多五次续写。
        self.assertEqual(prefixes[1], prefixes[2])
        self.assertEqual(prefixes[4], prefixes[5])
        self.assertEqual([entity["name"] for entity in spec["entities"]], names)
        self.assertEqual(len(spec["relations"]), 27)

    def test_siliconflow_reformatted_reply_must_preserve_saved_records(self):
        saved = '{"title":"选课","entities":[{"name":"学生","attrs":["*编号"]}'
        complete = {"title": "选课", "entities": [{"name": "学生", "attrs": ["*编号"]}, {"name": "课程"}],
                    "relations": [{"name": "选修", "a": "学生", "b": "课程"}]}
        replacement = {**complete, "entities": [{"name": "读者"}, {"name": "图书"}]}
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=[
                stream_reply(saved + ',{"name":"课', complete=False),
                stream_reply(json.dumps(replacement, ensure_ascii=False, indent=2)),
                stream_reply(json.dumps(complete, ensure_ascii=False, indent=2)),
            ],
        ) as http:
            spec = generate(GenerateRequest(text="学生选课"))["spec"]

        self.assertEqual(http.call_count, 3)
        self.assertEqual([entity["name"] for entity in spec["entities"]], ["学生", "课程"])

    def test_siliconflow_switches_to_validated_record_pages_when_continuation_stalls(self):
        prefix = '{"title":"选课","entities":[{"name":"学生","attrs":["*编号"]}'
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=[
                stream_reply(prefix + ',{"name":"课', complete=False),
                stream_reply("请重新生成。"),
                stream_reply(',{"name":"课程"},{"name":"学', complete=False),
                stream_reply('{"重写内容":"无法拼接', complete=False),
                stream_reply("请重新生成。"),
                stream_reply('{"name":"学院"}\n{"name":', complete=False),
                stream_reply('{"name":"学院","attrs":["别的属性"]}\n{"done":true}'),
                stream_reply('{"name":"选修","a":"学生","b":"课程"}\n'
                             '{"name":"错误联系","a":"学生","b":"未知实体"}\n{"done":true}'),
                stream_reply('{"name":"选修","entities":["学生","课程"]}\n'
                             '{"name":"开设","a":"学院","b":"课程"}\n{"done":true}', complete=False),
            ],
        ) as http:
            spec = generate(GenerateRequest(text="学生选课，学院开设课程"))["spec"]

        self.assertEqual(http.call_count, 9)
        self.assertEqual([entity["name"] for entity in spec["entities"]], ["学生", "课程", "学院"])
        self.assertEqual(spec["entities"][0]["attrs"], [{"name": "编号", "pk": True}])
        self.assertEqual([relation["name"] for relation in spec["relations"]], ["选修", "开设"])
        self.assertEqual(http.call_args.kwargs["timeout"], 18)
        final_context = json.loads(json.loads(http.call_args.args[0].data)["messages"][-1]["content"])
        self.assertEqual(final_context["当前阶段"], "relations")
        self.assertEqual([r["name"] for r in final_context["已提交规格"]["relations"]], ["选修"])

    def test_siliconflow_keeps_complete_specs_when_done_event_is_missing(self):
        raw = SAMPLE_PATH.read_text(encoding="utf-8")
        for finish_reason in (True, False):
            with self.subTest(finish_reason=finish_reason), patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
                "er_generator.urllib.request.urlopen",
                return_value=stream_reply(raw[:37], raw[37:], complete=finish_reason, done=False),
            ) as http:
                spec = generate(GenerateRequest(text="学生选课，记录成绩"))["spec"]
                http.assert_called_once()
                self.assertEqual(spec["relations"][0]["attrs"], ["成绩"])

    def test_duplicate_entity_pages_require_explicit_completion_audit(self):
        prefix = '{"entities":[{"name":"学生"},{"name":"课程"}'
        for confirmed, targeted_success in ((True, False), (False, True), (False, False)):
            with self.subTest(confirmed=confirmed, targeted_success=targeted_success):
                replies = [stream_reply(prefix + ',', complete=False),
                           stream_reply('无法续写'), stream_reply('无法续写'),
                           stream_reply('{"name":"学生"}'), stream_reply('{"name":"课程"}'),
                           model_reply('{"entities":[{"name":"学生"}]}'),
                           model_reply('```json\n' + json.dumps({'done': confirmed, 'missing': [] if confirmed else ['学院']}) + '\n```')]
                if confirmed:
                    replies.append(stream_reply('{"name":"选修","a":"学生","b":"课程"}\n{"done":true}'))
                else:
                    replies.append(model_reply(json.dumps({'entities': [{'name': '学院' if targeted_success else '学生'}]})))
                    if targeted_success:
                        replies.extend([model_reply('{"done":true}'), model_reply(
                            '{"relations":[{"name":"选修","a":"学生","b":"课程"},'
                            '{"name":"开设","a":"学院","b":"课程"}],"done":true}')])
                with patch.dict('os.environ', SILICONFLOW_ENV, clear=True), patch(
                    'er_generator.urllib.request.urlopen', side_effect=replies
                ) as http:
                    if confirmed or targeted_success:
                        spec = generate(GenerateRequest(text='学生选课，学院开设课程' if targeted_success else '学生选课'))['spec']
                        self.assertEqual([item['name'] for item in spec['entities']],
                                         ['学生', '课程', '学院'] if targeted_success else ['学生', '课程'])
                        self.assertEqual(spec['relations'][0]['name'], '选修')
                    else:
                        with self.assertRaises(HTTPException):
                            generate(GenerateRequest(text='学生选课'))
                    self.assertEqual(http.call_count, len(replies))
                    if not confirmed:
                        request = json.loads(http.call_args_list[7].args[0].data)
                        self.assertFalse(request['stream'])
                        self.assertEqual(json.loads(request['messages'][-1]['content'])['指定补全名称'], '学院')

    def test_recovery_switches_to_relations_as_soon_as_entity_capacity_is_reached(self):
        names = [f"菜品模块{i}" for i in range(24)]
        entities = [{"name": name} for name in names]
        relations = [{"name": "关联", "a": a, "b": b} for a, b in zip(names, names[1:])]
        for initially_full in (True, False):
            with self.subTest(initially_full=initially_full):
                prefix = json.dumps({"entities": entities if initially_full else entities[:-1]}, ensure_ascii=False)[:-2]
                replies = [stream_reply(prefix + ',{"name":', complete=False)]
                if not initially_full:
                    replies.extend([stream_reply("无法续写"), stream_reply("无法续写"),
                                    stream_reply(json.dumps({"entities": [entities[-1], {"name": "额外实体"}]},
                                                            ensure_ascii=False), complete=False)])
                replies.append(model_reply(json.dumps({"relations": relations, "done": True}, ensure_ascii=False)))
                with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
                    "er_generator.urllib.request.urlopen", side_effect=replies
                ) as http:
                    result = generate(GenerateRequest(text="设计完整菜品模块及其关联"))["spec"]

                self.assertEqual([entity["name"] for entity in result["entities"]], names)
                self.assertEqual(len(result["relations"]), 23)
                self.assertEqual(http.call_count, len(replies))
                body = json.loads(http.call_args.args[0].data)
                self.assertFalse(body["stream"])
                self.assertEqual(json.loads(body["messages"][-1]["content"])["当前阶段"], "relations")
                if not initially_full:
                    page = json.loads(http.call_args_list[-2].args[0].data)["messages"][-1]["content"]
                    self.assertEqual(json.loads(page)["本轮最多新增"], 1)

    def test_siliconflow_recovers_records_from_wrapped_and_interrupted_pages(self):
        prefix = '{"title":"选课","entities":[{"name":"学生","attrs":["*编号"]}'
        replies = [
            stream_reply('{"', complete=False),
            stream_reply(prefix + ',{"name":"课', complete=False),
            stream_reply("请重新生成。"),
            stream_reply("请重新生成。"),
            stream_reply('{"entities":[{"name":"课程"},{"name":"学', complete=False),
            stream_reply("暂无可用记录"),
            stream_reply('{"name":"学生"}\n{"done":false}'),
            model_reply('{"entities":[{"name":"学院"}],"done":true}'),
            model_reply('{"relations":['
                        '{"name":"错误","a":"学生","b":"未知实体"},'
                        '{"name":"选修","a":"学生","b":"课程"}],"done":true}'),
            model_reply('[{"name":"开设","a":"学院","b":"课程"}]\n{"done":true}'),
        ]
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=replies
        ) as http:
            spec = generate(GenerateRequest(text="学生选课，学院开设课程"))["spec"]

        self.assertEqual(http.call_count, len(replies))
        for index, call in enumerate(http.call_args_list):
            request = call.args[0]
            body = json.loads(request.data)
            self.assertEqual(request.full_url, "https://api.siliconflow.cn/v1/chat/completions")
            self.assertIs(body["stream"], index < 7)
            self.assertIs(body["enable_thinking"], False)
            self.assertEqual(request.get_header("Accept"), "text/event-stream" if index < 7 else "application/json")
        last_attempt = json.loads(http.call_args_list[7].args[0].data)["messages"]
        self.assertIn("改用一个紧凑 JSON 对象", last_attempt[0]["content"])
        self.assertEqual(json.loads(last_attempt[-1]["content"])["本轮最多新增"], 1)
        self.assertEqual([entity["name"] for entity in spec["entities"]], ["学生", "课程", "学院"])
        self.assertEqual(spec["entities"][0]["attrs"], [{"name": "编号", "pk": True}])
        self.assertEqual([relation["name"] for relation in spec["relations"]], ["选修", "开设"])

    def test_siliconflow_can_parse_consecutive_data_lines(self):
        raw = SAMPLE_PATH.read_text(encoding="utf-8")
        response = stream_reply(raw[:37], raw[37:], complete=False)
        response.write(response.getvalue().replace(b"\r\n\r\n", b"\r\n"))
        response.truncate()
        response.seek(0)
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", return_value=response
        ):
            spec = generate(GenerateRequest(text="学生选课，记录成绩"))["spec"]
        self.assertEqual(spec["relations"][0]["attrs"], ["成绩"])

    def test_siliconflow_early_close_includes_safe_counts_and_trace(self):
        response = stream_reply('{"incomplete":', complete=False)
        response.headers["x-siliconcloud-trace-id"] = "trace-example_42"
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen",
            side_effect=[stream_reply('{"incomplete":', complete=False), response],
        ), self.assertRaises(HTTPException) as caught:
            generate(GenerateRequest(text="学生选课"))
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("2 个事件、14 个正文字符", caught.exception.detail)
        self.assertIn("trace-example_42", caught.exception.detail)
        self.assertNotIn("incomplete", caught.exception.detail)

    def test_siliconflow_retries_overload_and_reports_auth_failure_immediately(self):
        raw = SAMPLE_PATH.read_text(encoding="utf-8")
        for status in (503, 401):
            with self.subTest(status=status), patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
                "er_generator.urllib.request.urlopen",
                side_effect=[HTTPError("https://api.siliconflow.cn", status, "error", {}, None), stream_reply(raw)],
            ) as http:
                if status == 503:
                    self.assertEqual(len(generate(GenerateRequest(text="学生选课"))["spec"]["entities"]), 2)
                    self.assertEqual(http.call_count, 2)
                else:
                    with self.assertRaises(HTTPException) as caught:
                        generate(GenerateRequest(text="学生选课"))
                    self.assertIn("401", caught.exception.detail)
                    http.assert_called_once()

    def test_siliconflow_timeout_retries_once_and_reports_connection_failure(self):
        failures = [URLError(TimeoutError()), ConnectionResetError("private details")]
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen", side_effect=failures
        ) as http, self.assertRaises(HTTPException) as caught:
            generate(GenerateRequest(text="设计图书系统"))

        self.assertEqual(http.call_count, 2)
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("ConnectionResetError", caught.exception.detail)
        self.assertNotIn("private", caught.exception.detail)

    def test_oversized_retry_response_replans_without_resending_invalid_json(self):
        names = [f"模块{i}" for i in range(25)]
        oversized = json.dumps({
            "entities": [{"name": name} for name in names],
            "relations": [{"a": a, "b": b} for a, b in zip(names, names[1:])],
        }, ensure_ascii=False)
        with patch.dict("os.environ", SILICONFLOW_ENV, clear=True), patch(
            "er_generator.urllib.request.urlopen",
            side_effect=[RemoteDisconnected(), model_reply(oversized), RemoteDisconnected()],
        ) as http, self.assertRaises(HTTPException) as caught:
            generate(GenerateRequest(text="设计库存与订单系统"))

        self.assertEqual(http.call_count, 3)
        initial = json.loads(http.call_args_list[0].args[0].data)["messages"]
        repair = json.loads(http.call_args_list[2].args[0].data)["messages"]
        self.assertIn("硬性约束", initial[0]["content"])
        self.assertIn("保留到 24 个", initial[0]["content"])
        self.assertIn("最多 40 条联系", initial[0]["content"])
        self.assertEqual([message["role"] for message in repair], ["system", "user"])
        self.assertIn("设计库存与订单系统", repair[1]["content"])
        self.assertIn("实际生成 25 个实体", repair[1]["content"])
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("实际生成 25 个实体", caught.exception.detail)
        self.assertIn("修正请求失败", caught.exception.detail)

    def test_missing_model_configuration_and_invalid_input(self):
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(HTTPException) as caught:
            generate(GenerateRequest(text="设计图书系统"))
        self.assertEqual(caught.exception.status_code, 503)

        for text in ("   ", "长" * 4001):
            with self.subTest(length=len(text)), self.assertRaises(ValidationError):
                GenerateRequest(text=text)


if __name__ == "__main__":
    unittest.main()
