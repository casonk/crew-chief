"""Tests for crew_chief.client — all offline, no real Ollama service required."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from crew_chief.client import CrewChiefClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_urlopen_mock(response_body: dict):
    """Return a context-manager mock that yields a fake HTTP response."""
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps(response_body).encode()
    mock_resp.status = 200
    return mock_resp


# ---------------------------------------------------------------------------
# CrewChiefClient unit tests
# ---------------------------------------------------------------------------


class TestCrewChiefClientInit(unittest.TestCase):
    def test_defaults(self):
        c = CrewChiefClient()
        self.assertEqual(c.base_url, "http://localhost:11434")
        self.assertEqual(c.model, "llama3.2")
        self.assertEqual(c.timeout, 60)

    def test_custom_values(self):
        c = CrewChiefClient(base_url="http://remote:11434/", model="mistral", timeout=30)
        self.assertEqual(c.base_url, "http://remote:11434")  # trailing slash stripped
        self.assertEqual(c.model, "mistral")
        self.assertEqual(c.timeout, 30)


class TestCrewChiefClientGenerate(unittest.TestCase):
    def test_generate_returns_response_field(self):
        mock_resp = _make_urlopen_mock({"response": "Hello, world!"})
        with patch("urllib.request.urlopen", return_value=mock_resp):
            c = CrewChiefClient()
            result = c.generate("Say hi")
        self.assertEqual(result, "Hello, world!")

    def test_generate_missing_response_field(self):
        mock_resp = _make_urlopen_mock({})
        with patch("urllib.request.urlopen", return_value=mock_resp):
            c = CrewChiefClient()
            result = c.generate("Say hi")
        self.assertEqual(result, "")

    def test_generate_sends_correct_payload(self):
        captured = {}
        mock_resp = _make_urlopen_mock({"response": "ok"})

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["data"] = json.loads(req.data)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            c = CrewChiefClient(model="phi3")
            c.generate("test prompt")

        self.assertIn("/api/generate", captured["url"])
        self.assertEqual(captured["data"]["model"], "phi3")
        self.assertEqual(captured["data"]["prompt"], "test prompt")
        self.assertFalse(captured["data"]["stream"])


class TestCrewChiefClientChat(unittest.TestCase):
    def test_chat_returns_message_content(self):
        body = {"message": {"role": "assistant", "content": "Sure!"}}
        mock_resp = _make_urlopen_mock(body)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            c = CrewChiefClient()
            result = c.chat([{"role": "user", "content": "help"}])
        self.assertEqual(result, "Sure!")

    def test_chat_missing_message_field(self):
        mock_resp = _make_urlopen_mock({})
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = CrewChiefClient().chat([])
        self.assertEqual(result, "")


class TestCrewChiefClientHealth(unittest.TestCase):
    def test_health_true_on_200(self):
        mock_resp = _make_urlopen_mock({})
        mock_resp.status = 200
        with patch("urllib.request.urlopen", return_value=mock_resp):
            self.assertTrue(CrewChiefClient().health())

    def test_health_false_on_connection_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            self.assertFalse(CrewChiefClient().health())


class TestCrewChiefClientListModels(unittest.TestCase):
    def test_list_models_extracts_names(self):
        body = {"models": [{"name": "llama3.2"}, {"name": "mistral"}]}
        mock_resp = _make_urlopen_mock(body)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = CrewChiefClient().list_models()
        self.assertEqual(result, ["llama3.2", "mistral"])

    def test_list_models_empty(self):
        mock_resp = _make_urlopen_mock({"models": []})
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = CrewChiefClient().list_models()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
