import queue
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app import AgentApp


def tool_call(name, arguments):
    import json

    return {
        "function": {
            "name": name,
            "arguments": json.dumps(arguments),
        }
    }


class AgentToolTests(unittest.TestCase):
    def setUp(self):
        self.agent = AgentApp.__new__(AgentApp)

    @patch("app.urllib.request.urlopen")
    def test_openai_request_uses_configured_api_key(self, urlopen):
        self.agent.api_key = "test-key"
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = b'{"choices": []}'

        self.agent._call_openai([])

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")

    @patch("app.subprocess.run")
    def test_speech_recognition_queues_transcribed_text(self, run):
        self.agent.events = queue.Queue()
        run.return_value.returncode = 0
        run.return_value.stdout = "Hello there\n"
        run.return_value.stderr = ""

        self.agent._recognize_speech()

        self.assertEqual(self.agent.events.get_nowait(), ("recognized", "Hello there"))

    @patch("app.subprocess.Popen")
    def test_open_app_uses_fixed_command_without_shell(self, popen):
        result = self.agent._run_tool(tool_call("open_app", {"app": "notepad"}))

        self.assertEqual(result, "Opened Notepad.")
        popen.assert_called_once_with(["notepad.exe"], shell=False)

    @patch("app.webbrowser.open")
    def test_whatsapp_message_opens_encoded_draft(self, open_browser):
        open_browser.return_value = True
        result = self.agent._run_tool(
            tool_call(
                "draft_whatsapp_message",
                {"phone_number": "+1 (555) 123-4567", "message": "Hello there"},
            )
        )

        self.assertIn("not sent", result)
        url = open_browser.call_args.args[0]
        self.assertEqual(urlparse(url).path, "/15551234567")
        self.assertEqual(parse_qs(urlparse(url).query)["text"], ["Hello there"])

    @patch("app.webbrowser.open")
    def test_invalid_whatsapp_number_does_not_open_browser(self, open_browser):
        result = self.agent._run_tool(
            tool_call(
                "draft_whatsapp_message",
                {"phone_number": "not-a-number", "message": "Hello"},
            )
        )

        self.assertIn("international format", result)
        open_browser.assert_not_called()

    @patch("app.subprocess.Popen")
    def test_unapproved_app_is_not_launched(self, popen):
        result = self.agent._run_tool(tool_call("open_app", {"app": "powershell"}))

        self.assertIn("not on the approved list", result)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
