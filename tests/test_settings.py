import tempfile
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("webview", types.ModuleType("webview"))
import main as app_main

Bridge = app_main.Bridge


class SettingsTests(unittest.TestCase):
    def bridge(self, config=None):
        bridge = Bridge.__new__(Bridge)
        bridge._config = config or {}
        bridge._lock = threading.RLock()
        return bridge

    def test_selected_api_modes_require_an_https_endpoint(self):
        bridge = self.bridge()
        responses = bridge.save_settings({"api_mode": "responses", "responses_url": ""})
        compatible = bridge.save_settings({"api_mode": "chat_completions", "chat_completions_url": "http://api.test/v1/chat/completions"})

        self.assertFalse(responses["ok"])
        self.assertIn("Responses API", responses["error"])
        self.assertFalse(compatible["ok"])
        self.assertIn("Chat Completions", compatible["error"])

    @patch.object(app_main.storage, "save_config")
    def test_valid_selected_endpoint_is_saved(self, save_config):
        bridge = self.bridge()
        bridge.get_state = lambda: {"ok": True}

        result = bridge.save_settings({
            "api_mode": "chat_completions",
            "chat_completions_url": "https://api.example.edu/v1/chat/completions",
        })

        self.assertTrue(result["ok"])
        self.assertEqual(bridge._config["chat_completions_url"], "https://api.example.edu/v1/chat/completions")
        save_config.assert_called_once()

    def test_each_thread_keeps_its_selected_model(self):
        with tempfile.TemporaryDirectory() as temp:
            thread_dir = Path(temp) / "threads"
            thread_dir.mkdir()
            with patch.object(app_main.storage, "THREADS_DIR", thread_dir):
                bridge = self.bridge({"api_mode": "chat_completions", "model": "gemini-3.8-flash"})
                thread = bridge.new_thread()
                bridge._config["model"] = "gpt-6-astra"

                loaded = bridge.load_thread(thread["id"])
                self.assertEqual(loaded["model"], "gemini-3.8-flash")
                self.assertEqual(loaded["updated"], thread["updated"])
                changed = bridge.set_thread_model(thread["id"], "claude-sonnet-5-5")
                self.assertEqual(changed["model"], "claude-sonnet-5-5")
                self.assertEqual(bridge.load_thread(thread["id"])["model"], "claude-sonnet-5-5")

                # 1.9 이전에 저장한 잘못된 Claude ID(점)는 게이트웨이의 ID(-)로 바뀐다
                old = app_main.storage.new_thread()
                old["model"] = "claude-opus-5.5"
                app_main.storage.save_thread(old)
                self.assertEqual(bridge.load_thread(old["id"])["model"], "claude-opus-5-5")

                legacy = app_main.storage.new_thread()
                legacy_updated = legacy["updated"]
                migrated = bridge.load_thread(legacy["id"])
                self.assertEqual(migrated["model"], "gpt-6-astra")
                self.assertEqual(migrated["updated"], legacy_updated)

    def test_responses_mode_rejects_models_outside_its_supported_set(self):
        bridge = self.bridge({"api_mode": "responses"})
        result = bridge.set_thread_model("missing", "claude-sonnet-5-5")
        self.assertFalse(result["ok"])
        self.assertIn("지원하지 않는", result["error"])

    @patch.object(app_main.storage, "save_config")
    def test_base_url_is_saved_as_full_endpoint(self, _save_config):
        bridge = self.bridge()
        bridge.get_state = lambda: {"ok": True}
        result = bridge.save_settings({"api_mode": "chat_completions", "chat_completions_url": "https://api.example.edu/v1/"})
        self.assertTrue(result["ok"])
        self.assertEqual(bridge._config["chat_completions_url"], "https://api.example.edu/v1/chat/completions")

    @patch.object(app_main.storage, "save_config")
    @patch.object(app_main.api, "list_models", return_value=["gpt-6.1-sol", "new-model-x"])
    def test_server_models_replace_the_builtin_list_when_saved(self, list_models, save_config):
        bridge = self.bridge({"api_mode": "chat_completions", "api_key": "saved-key"})
        result = bridge.refresh_models({"chat_completions_url": "https://api.example.edu/v1"})

        self.assertTrue(result["ok"])
        list_models.assert_called_once_with("saved-key", "https://api.example.edu/v1/chat/completions")
        self.assertEqual([m["id"] for m in result["models"]], ["gpt-6.1-sol", "new-model-x"])
        # 불러오기만 하고 저장하지 않으면(설정 창 취소) 아무것도 바뀌지 않는다
        save_config.assert_not_called()
        self.assertNotIn("server_models", bridge._config)
        self.assertNotIn("chat_completions_url", bridge._config)

        bridge.get_state = lambda: {"ok": True}
        bridge.save_settings({"chat_completions_url": result["chat_completions_url"],
                              "server_models": [m["id"] for m in result["models"]], "model": "new-model-x"})
        self.assertEqual(bridge._model_ids("chat_completions"), {"gpt-6.1-sol", "new-model-x"})
        self.assertEqual(bridge._config["model"], "new-model-x")
        self.assertEqual({m for m, _ in bridge._models("responses")}, {m for m, _ in app_main.RESPONSES_MODELS})

        bridge.save_settings({"chat_completions_url": "https://other.example.edu/v1"})
        self.assertNotIn("server_models", bridge._config)

    @patch.object(app_main.storage, "save_config")
    def test_old_a1_default_moves_to_the_openai_compatible_api_once(self, save_config):
        bridge = self.bridge({"api_mode": "a1", "model": "claude-sonnet-5.5"})
        bridge._migrate_config()
        self.assertEqual(bridge._config["api_mode"], "chat_completions")
        self.assertEqual(bridge._config["model"], "claude-sonnet-5-5")
        self.assertEqual(app_main.ApiSettings.from_config(bridge._config).chat_completions_url,
                         app_main.api.DEFAULT_CHAT_COMPLETIONS_URL)
        bridge._config["api_mode"] = "a1"  # 옮긴 뒤 사용자가 다시 a1을 고르면 그대로 둔다
        bridge._migrate_config()
        self.assertEqual(bridge._config["api_mode"], "a1")

    def test_refresh_models_needs_key_and_https_url(self):
        with patch.dict(app_main.os.environ, {}, clear=True):
            self.assertFalse(self.bridge().refresh_models({"chat_completions_url": "https://api.example.edu/v1"})["ok"])
        bad = self.bridge({"api_key": "k"}).refresh_models({"chat_completions_url": "http://api.example.edu/v1"})
        self.assertFalse(bad["ok"])

    @patch.object(app_main.api, "list_models", side_effect=app_main.ApiError("API 오류 401"))
    def test_refresh_models_reports_server_errors(self, _list_models):
        result = self.bridge({"api_key": "k"}).refresh_models({"chat_completions_url": "https://api.example.edu/v1"})
        self.assertFalse(result["ok"])
        self.assertIn("401", result["error"])


if __name__ == "__main__":
    unittest.main()
