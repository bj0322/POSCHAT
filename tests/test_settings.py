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
                changed = bridge.set_thread_model(thread["id"], "claude-sonnet-5.5")
                self.assertEqual(changed["model"], "claude-sonnet-5.5")
                self.assertEqual(bridge.load_thread(thread["id"])["model"], "claude-sonnet-5.5")

                legacy = app_main.storage.new_thread()
                legacy_updated = legacy["updated"]
                migrated = bridge.load_thread(legacy["id"])
                self.assertEqual(migrated["model"], "gpt-6-astra")
                self.assertEqual(migrated["updated"], legacy_updated)

    def test_responses_mode_rejects_models_outside_its_supported_set(self):
        bridge = self.bridge({"api_mode": "responses"})
        result = bridge.set_thread_model("missing", "claude-sonnet-5.5")
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
    def test_server_models_replace_the_builtin_list(self, list_models, _save_config):
        bridge = self.bridge({"api_mode": "chat_completions", "api_key": "saved-key"})
        result = bridge.refresh_models({"chat_completions_url": "https://api.example.edu/v1"})

        self.assertTrue(result["ok"])
        list_models.assert_called_once_with("saved-key", "https://api.example.edu/v1/chat/completions")
        self.assertEqual([m["id"] for m in result["models"]], ["gpt-6.1-sol", "new-model-x"])
        self.assertEqual(bridge._model_ids("chat_completions"), {"gpt-6.1-sol", "new-model-x"})
        self.assertEqual(bridge._default_model(), "gpt-6.1-sol")
        self.assertEqual({m for m, _ in bridge._models("responses")}, {m for m, _ in app_main.RESPONSES_MODELS})

        bridge.get_state = lambda: {"ok": True}
        bridge.save_settings({"chat_completions_url": "https://other.example.edu/v1"})
        self.assertNotIn("server_models", bridge._config)

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
