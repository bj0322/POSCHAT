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


if __name__ == "__main__":
    unittest.main()
