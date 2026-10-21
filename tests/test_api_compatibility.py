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
            "claude-opus-5.5",
            "claude-sonnet-5.5",
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
            model="claude-sonnet-5.5",
            stream=False,
        )

        text = api.ask("api-key", "Hi", settings=settings)

        self.assertEqual(text, "Hello")
        args, kwargs = post.call_args
        self.assertEqual(args[0], settings.chat_completions_url)
        self.assertEqual(args[1]["Authorization"], "Bearer api-key")
        self.assertEqual(args[2]["model"], "claude-sonnet-5.5")
        self.assertEqual(args[2]["messages"], [{"role": "user", "content": "Hi"}])

    def test_reads_openai_chat_stream_chunks(self):
        obj = {"choices": [{"delta": {"content": "안녕"}}]}
        self.assertEqual(api._chunk(None, json.dumps(obj)), ("delta", "안녕"))


if __name__ == "__main__":
    unittest.main()
