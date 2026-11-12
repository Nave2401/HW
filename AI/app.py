import json
import os
import queue
import re
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk


MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
API_URL = "https://api.openai.com/v1/chat/completions"
SYSTEM_PROMPT = (
    "You are a helpful Windows desktop assistant. Answer questions clearly. "
    "You can request to open an approved app or prepare a WhatsApp message. "
    "Never claim an action happened unless its tool result confirms it. "
    "Ask for missing details before requesting an action. WhatsApp messages "
    "are opened as drafts and are never sent by this app."
)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Open one of the approved Windows apps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app": {
                        "type": "string",
                        "enum": ["whatsapp", "notepad", "calculator", "edge", "chrome"],
                        "description": "The app to open.",
                    }
                },
                "required": ["app"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_whatsapp_message",
            "description": (
                "Open a WhatsApp chat with a prefilled message draft. "
                "The user must send it manually in WhatsApp."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": "Recipient number in international format, including country code.",
                    },
                    "message": {
                        "type": "string",
                        "description": "The exact message to prepare as a draft.",
                    },
                },
                "required": ["phone_number", "message"],
                "additionalProperties": False,
            },
        },
    },
]
APP_COMMANDS = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "edge": ["msedge.exe"],
    "chrome": ["chrome.exe"],
}
APP_LABELS = {
    "whatsapp": "WhatsApp",
    "notepad": "Notepad",
    "calculator": "Calculator",
    "edge": "Microsoft Edge",
    "chrome": "Google Chrome",
}


class AgentApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Chat")
        self.root.geometry("900x700")
        self.root.minsize(620, 480)
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.events = queue.Queue()
        self.busy = False
        self.listening = False
        self.closing = False
        self.voice_enabled = True
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._set_status("Ready" if self.api_key else "Add your OpenAI API key to start")
        self.root.after(100, self._poll_events)

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.root, padding=(12, 10))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(0, weight=1)
        ttk.Label(toolbar, text="AI Chat", font=("Segoe UI", 15, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.voice_toggle = ttk.Button(toolbar, text="Voice: On", command=self._toggle_voice)
        self.voice_toggle.grid(row=0, column=1, padx=4)
        ttk.Button(toolbar, text="API key", command=self._set_api_key).grid(row=0, column=2, padx=4)
        ttk.Button(toolbar, text="New chat", command=self._new_chat).grid(row=0, column=3, padx=4)

        chat_frame = ttk.Frame(self.root, padding=(12, 0, 12, 8))
        chat_frame.grid(row=1, column=0, sticky="nsew")
        chat_frame.columnconfigure(0, weight=1)
        chat_frame.rowconfigure(0, weight=1)
        self.chat = tk.Text(
            chat_frame,
            wrap="word",
            state="disabled",
            padx=12,
            pady=12,
            font=("Segoe UI", 10),
            background="#ffffff",
            relief="solid",
            borderwidth=1,
        )
        scrollbar = ttk.Scrollbar(chat_frame, orient="vertical", command=self.chat.yview)
        self.chat.configure(yscrollcommand=scrollbar.set)
        self.chat.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.chat.tag_configure("user", foreground="#155eef", spacing1=10, spacing3=8)
        self.chat.tag_configure("assistant", foreground="#202124", spacing1=10, spacing3=8)
        self.chat.tag_configure("notice", foreground="#a33b00", spacing1=8, spacing3=8)
        self._append("Assistant", "Hi! Ask me anything, or ask me to open an app. I’ll ask before taking an action.")

        composer = ttk.Frame(self.root, padding=(12, 4, 12, 8))
        composer.grid(row=2, column=0, sticky="ew")
        composer.columnconfigure(0, weight=1)
        self.input = tk.Text(composer, height=3, wrap="word", font=("Segoe UI", 10))
        self.input.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.input.bind("<Return>", self._send_from_shortcut)
        self.input.bind("<Control-Return>", self._send_from_shortcut)
        self.listen_button = ttk.Button(composer, text="Start talking", command=self._listen)
        self.listen_button.grid(row=0, column=1, sticky="se", padx=(0, 6))
        self.send_button = ttk.Button(composer, text="Send", command=self._send)
        self.send_button.grid(row=0, column=2, sticky="se")

        self.status = ttk.Label(self.root, text="", anchor="w", padding=(12, 3))
        self.status.grid(row=3, column=0, sticky="ew")

    def _append(self, speaker, text):
        tag = "user" if speaker == "You" else "assistant"
        self.chat.configure(state="normal")
        self.chat.insert("end", f"{speaker}\n", tag)
        self.chat.insert("end", f"{text}\n\n", tag)
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _set_status(self, text):
        self.status.configure(text=text)

    def _toggle_voice(self):
        self.voice_enabled = not self.voice_enabled
        self.voice_toggle.configure(text="Voice: On" if self.voice_enabled else "Voice: Off")
        self._set_status("Voice enabled" if self.voice_enabled else "Voice muted")

    def _speak(self, text):
        if not self.voice_enabled or not text:
            return
        safe_text = text.replace("'", "''").replace("`", "``")
        command = (
            "$voice = New-Object -ComObject SAPI.SpVoice; "
            f"$voice.Speak('{safe_text}')"
        )
        threading.Thread(
            target=lambda: subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                start_new_session=True,
            ),
            daemon=True,
        ).start()

    def _set_api_key(self):
        value = simpledialog.askstring(
            "OpenAI API key",
            "Paste your OpenAI API key. It is kept in memory only and is not saved to disk.",
            parent=self.root,
            show="*",
        )
        if value is not None:
            self.api_key = value.strip()
            self._set_status("API key set for this session" if self.api_key else "API key cleared")

    def _new_chat(self):
        if self.busy:
            return
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        self._append("Assistant", "New chat started. What can I help with?")

    def _send_from_shortcut(self, _event):
        self._send()
        return "break"

    def _listen(self):
        if self.busy:
            return
        self.busy = True
        self.listening = True
        self.send_button.configure(state="disabled")
        self.listen_button.configure(state="disabled")
        self._set_status("Listening… Speak now")
        threading.Thread(target=self._recognize_speech, daemon=True).start()

    def _recognize_speech(self):
        script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    Add-Type -AssemblyName System.Speech
    $recognizer = New-Object System.Speech.Recognition.SpeechRecognitionEngine
    try {
        $grammar = New-Object System.Speech.Recognition.DictationGrammar
        $recognizer.LoadGrammar($grammar)
        $recognizer.SetInputToDefaultAudioDevice()
        $result = $recognizer.Recognize([TimeSpan]::FromSeconds(15))
        if ($null -ne $result) {
            [Console]::WriteLine($result.Text)
        }
    } finally {
        $recognizer.Dispose()
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
            if result.returncode:
                error = result.stderr.strip() or "Windows speech recognition could not start."
                self.events.put(("listen_error", error))
                return
            text = result.stdout.strip()
            if not text:
                self.events.put(("listen_error", "I didn't catch that. Please try again."))
                return
            self.events.put(("recognized", text))
        except subprocess.TimeoutExpired:
            self.events.put(("listen_error", "Listening timed out. Please try again."))
        except OSError as exc:
            self.events.put(("listen_error", f"Could not start speech recognition: {exc}"))

    def _send(self):
        if self.busy:
            return
        text = self.input.get("1.0", "end").strip()
        if not text:
            return
        if not self.api_key:
            messagebox.showwarning(
                "API key required",
                "Set your OpenAI API key with the API key button, or set OPENAI_API_KEY before launching.",
                parent=self.root,
            )
            return

        self.input.delete("1.0", "end")
        self._append("You", text)
        self.busy = True
        self.send_button.configure(state="disabled")
        self._set_status("Thinking…")
        prior_messages = list(self.messages)
        threading.Thread(
            target=self._request_reply,
            args=(prior_messages, text),
            daemon=True,
        ).start()

    def _request_reply(self, prior_messages, user_text):
        messages = prior_messages + [{"role": "user", "content": user_text}]
        try:
            for _ in range(5):
                result = self._call_openai(messages)
                choices = result.get("choices")
                if not isinstance(choices, list) or not choices:
                    raise RuntimeError("OpenAI returned no choices.")

                choice = choices[0]
                assistant_message = choice.get("message") or {}
                if not isinstance(assistant_message, dict):
                    raise RuntimeError("OpenAI returned an invalid assistant message.")

                calls = assistant_message.get("tool_calls") or []
                if not calls:
                    reply = assistant_message.get("content")
                    if not isinstance(reply, str) or not reply.strip():
                        reply = "(The assistant returned an empty reply.)"
                    messages.append({"role": "assistant", "content": reply})
                    self.events.put(("done", messages, reply))
                    return

                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_message.get("content"),
                        "tool_calls": calls,
                    }
                )
                for call in calls:
                    approved, output = self._request_action_approval(call)
                    if approved:
                        output = self._run_tool(call)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": output,
                        }
                    )

            raise RuntimeError("The assistant reached the tool-call limit for one request.")
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _call_openai(self, messages):
        payload = json.dumps(
            {
                "model": MODEL,
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "parallel_tool_calls": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                error = json.loads(detail).get("error", {}).get("message", detail)
            except json.JSONDecodeError:
                error = detail
            raise RuntimeError(f"OpenAI API error ({exc.code}): {error}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not connect to OpenAI: {exc.reason}") from exc

        try:
            return json.loads(data)
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenAI returned an invalid response.") from exc

    def _request_action_approval(self, call):
        request = {"event": threading.Event(), "approved": False}
        self.events.put(("approval", call, request))
        request["event"].wait()
        if request["approved"]:
            return True, ""
        return False, "The user declined this action."

    def _run_tool(self, call):
        name = call.get("function", {}).get("name")
        try:
            arguments = json.loads(call.get("function", {}).get("arguments", "{}"))
        except json.JSONDecodeError:
            return "Action failed: invalid tool arguments."

        if not isinstance(arguments, dict):
            return "Action failed: invalid tool arguments."

        if name == "open_app":
            app = arguments.get("app")
            if app not in APP_LABELS:
                return "Action failed: app is not on the approved list."
            if app == "whatsapp":
                webbrowser.open("https://web.whatsapp.com")
            else:
                subprocess.Popen(APP_COMMANDS[app], shell=False)
            return f"Opened {APP_LABELS[app]}."

        if name == "draft_whatsapp_message":
            phone = re.sub(r"[\s()+-]", "", str(arguments.get("phone_number", "")))
            message = str(arguments.get("message", ""))
            if not phone.isdigit() or not 7 <= len(phone) <= 15:
                return "Action failed: enter the recipient's number in international format."
            if not message.strip() or len(message) > 4000:
                return "Action failed: message must contain 1 to 4000 characters."
            url = "https://wa.me/" + phone + "?" + urllib.parse.urlencode({"text": message})
            if not webbrowser.open(url):
                return "Could not open the WhatsApp draft in a browser."
            return "Opened a WhatsApp chat with the message filled in as a draft. It was not sent."

        return "Action failed: unknown tool."

    def _poll_events(self):
        if self.closing:
            return
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "approval":
                    _, call, request = event
                    request["approved"] = self._confirm_action(call)
                    request["event"].set()
                elif kind == "done":
                    _, self.messages, reply = event
                    self._append("Assistant", reply)
                    self._speak(reply)
                    self._finish_request("Ready")
                elif kind == "recognized":
                    self.listening = False
                    self._finish_request("Sending your message…")
                    self.input.delete("1.0", "end")
                    self.input.insert("1.0", event[1])
                    self._send()
                elif kind == "listen_error":
                    self.listening = False
                    self._append("Assistant", event[1])
                    self._finish_request("Speech recognition failed")
                elif kind == "error":
                    self._append("Assistant", f"Sorry, I couldn't complete that request.\n{event[1]}")
                    self._finish_request("Request failed")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _confirm_action(self, call):
        function = call.get("function", {})
        try:
            arguments = json.loads(function.get("arguments", "{}"))
        except json.JSONDecodeError:
            messagebox.showerror("Action blocked", "The requested action had invalid arguments.", parent=self.root)
            return False

        if not isinstance(arguments, dict):
            messagebox.showerror("Action blocked", "The requested action had invalid arguments.", parent=self.root)
            return False

        name = function.get("name")
        if name == "open_app" and arguments.get("app") in APP_LABELS:
            prompt = f"Open {APP_LABELS[arguments['app']]}?"
        elif name == "draft_whatsapp_message":
            phone = arguments.get("phone_number", "(missing number)")
            message = arguments.get("message", "(missing message)")
            prompt = (
                f"Open a WhatsApp draft for {phone}?\n\n"
                f"Message:\n{message}\n\n"
                "This will not send the message. You can review and send it in WhatsApp."
            )
        else:
            messagebox.showerror("Action blocked", "This action is not supported.", parent=self.root)
            return False

        return messagebox.askyesno("Confirm action", prompt, parent=self.root)

    def _finish_request(self, status):
        self.busy = False
        self.send_button.configure(state="normal")
        self.listen_button.configure(state="normal")
        self._set_status(status)

    def _close(self):
        self.closing = True
        self.root.destroy()


def main():
    root = tk.Tk()
    AgentApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
