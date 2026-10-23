import json
import unittest
from unittest.mock import Mock, patch

import api


class ChatCompletionsTests(unittest.TestCase):
    def test_adds_new_notice_models(self):
        model_ids = {model_id for model_id, _ in api.MODELS}
        self.assertTrue({
            "gpt-6.1-sol",
            "gpt-6-astra",
            "claude-opus-5-5",
            "claude-sonnet-5-5",
            "gemini-3.8-flash",
        }.issubset(model_ids))

    @patch("api._is_json", return_value=True)
    @patch("api._post")
    def test_sends_openai_compatible_request_and_reads_answer(self, post, _is_json):
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "Hello"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }
        post.return_value = response
        settings = api.ApiSettings(
            mode="chat_completions",
            chat_completions_url="https://genai.postech.ac.kr/v1/chat/completions",
            model="claude-sonnet-5-5",
            stream=False,
        )

        text = api.ask("api-key", "Hi", settings=settings)

        self.assertEqual(text, "Hello")
        args, kwargs = post.call_args
        self.assertEqual(args[0], settings.chat_completions_url)
        self.assertEqual(args[1]["Authorization"], "Bearer api-key")
        self.assertEqual(args[2]["model"], "claude-sonnet-5-5")
        self.assertEqual(args[2]["messages"], [{"role": "user", "content": "Hi"}])

    def test_reads_openai_chat_stream_chunks(self):
        obj = {"choices": [{"delta": {"content": "안녕"}}]}
        self.assertEqual(api._chunk(None, json.dumps(obj)), ("delta", "안녕"))

    @patch("api._post")
    def test_unreadable_chat_stream_is_an_api_error(self, post):
        response = Mock()
        response.headers = {"Content-Type": "text/event-stream"}
        response.iter_lines.return_value = [b"data: [DONE]", b""]
        post.return_value = response
        settings = api.ApiSettings(mode="chat_completions", chat_completions_url="https://api.test/v1/chat/completions")

        with self.assertRaises(api.ApiError):
            api.ask("api-key", "Hi", settings=settings, on_delta=lambda _text: None)


class EndpointTests(unittest.TestCase):
    def test_base_url_gets_the_call_path(self):
        chat = api.CHAT_COMPLETIONS_PATH
        self.assertEqual(api.endpoint_url("https://api.test/v1", chat), "https://api.test/v1/chat/completions")
        self.assertEqual(api.endpoint_url(" https://api.test/v1/ ", chat), "https://api.test/v1/chat/completions")
        self.assertEqual(api.endpoint_url("https://api.test/v1/models", chat), "https://api.test/v1/chat/completions")
        self.assertEqual(api.endpoint_url("https://api.test/v1/chat/completions", chat),
                         "https://api.test/v1/chat/completions")
        self.assertEqual(api.endpoint_url("https://api.test/a7/openai", api.RESPONSES_PATH),
                         "https://api.test/a7/openai/responses")
        self.assertEqual(api.endpoint_url("", chat), "")

    def test_query_string_stays_after_the_path(self):
        chat = api.CHAT_COMPLETIONS_PATH
        azure = "https://x.openai.azure.com/openai/deployments/d/chat/completions?api-version=2024-10-21"
        self.assertEqual(api.endpoint_url(azure, chat), azure)
        self.assertEqual(api.endpoint_url("https://api.test/v1/?key=1", chat), "https://api.test/v1/chat/completions?key=1")
        self.assertEqual(api.models_url(azure), "https://x.openai.azure.com/openai/deployments/d/models?api-version=2024-10-21")
        settings = api.ApiSettings.from_config({"chat_completions_url": azure})
        self.assertEqual(settings.chat_completions_url, azure)

    def test_saved_base_url_is_used_as_full_endpoint(self):
        settings = api.ApiSettings.from_config({"api_mode": "chat_completions", "chat_completions_url": "https://api.test/v1"})
        self.assertEqual(settings.chat_completions_url, "https://api.test/v1/chat/completions")

    def test_models_url_shares_the_base_url(self):
        self.assertEqual(api.models_url("https://api.test/v1/chat/completions"), "https://api.test/v1/models")
        self.assertEqual(api.models_url("https://api.test/v1"), "https://api.test/v1/models")

    @patch("api._request")
    def test_lists_models_from_openai_and_gateway_formats(self, request):
        response = Mock()
        request.return_value = response
        response.json.return_value = {"object": "list", "data": [{"id": "gpt-6.1-sol"}, {"id": "claude-opus-5-5"}]}
        self.assertEqual(api.list_models("key", "https://api.test/v1"), ["gpt-6.1-sol", "claude-opus-5-5"])
        args, _ = request.call_args
        self.assertEqual(args[:2], ("GET", "https://api.test/v1/models"))
        self.assertEqual(args[2]["Authorization"], "Bearer key")

        response.json.return_value = {"code": "0", "data": {"data": [{"id": "gemini-3.8-flash"}, "gpt-6-astra"]}}
        self.assertEqual(api.list_models("key", "https://api.test/v1"), ["gemini-3.8-flash", "gpt-6-astra"])

        response.json.return_value = {"data": []}
        with self.assertRaises(api.ApiError):
            api.list_models("key", "https://api.test/v1")

    def test_openai_compatible_calls_send_the_gateway_key_header(self):
        headers = api._auth_headers("k")
        self.assertEqual(headers["x-api-key"], "k")  # POSTECH 게이트웨이는 Bearer만으로는 'Token validation failed'
        self.assertEqual(headers["Authorization"], "Bearer k")

    def test_a1_error_marker_is_an_api_error(self):
        with self.assertRaisesRegex(api.ApiError, "10000"):
            api._check_a1_error('<div cls="error" attr="10000"></div>')
        api._check_a1_error("정상 답변")

    def test_credit_headers(self):
        info = api._credit({"x-role-ratelimit-credit-usage": "175", "x-role-ratelimit-credit-limit": "15000",
                            "x-role-ratelimit-credit-limit-interval": "WEEKLY"})
        self.assertEqual(info, {"usage": 175.0, "limit": 15000.0, "interval": "WEEKLY"})
        self.assertIsNone(api._credit({}))

    def test_unknown_model_ids_are_shown_as_is(self):
        self.assertEqual(api.model_label("claude-opus-5-5"), "Claude Opus 5.5")
        self.assertEqual(api.model_label("new-model-x"), "new-model-x")


if __name__ == "__main__":
    unittest.main()
