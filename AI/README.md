# AI Chat

A Windows desktop chat assistant that answers questions with OpenAI, remembers the current conversation, and can speak its replies. It can open approved apps after asking for confirmation and prepare WhatsApp messages as drafts; it never sends messages.

## Start

1. Install Python 3.10 or later.
2. Double-click `run.bat`.
3. In the app, select **API key** and paste your OpenAI API key. The key stays in memory for that run and is not saved to disk.
4. Type a message and press **Enter** or **Send**, or select **Talk** and speak. Recognized speech is sent automatically.
5. Use **Voice: On/Off** to control spoken replies.

Alternatively, set `OPENAI_API_KEY` in your environment before starting the app. You can set `OPENAI_MODEL` to use a different model supported by your OpenAI account; the default is `gpt-4o-mini`.

## Supported actions

- Open WhatsApp Web, Notepad, Calculator, Microsoft Edge, or Google Chrome.
- Prepare a WhatsApp draft using an international phone number and message text.

The assistant asks before each supported action. WhatsApp drafts open in a browser; check the recipient and text, then send manually in WhatsApp if you choose. This app does not read other apps, click their controls, or send messages automatically.

Voice input uses the Windows speech recognition engine and a microphone. The app uses only Python's standard library. The OpenAI API requires internet access and an API key; API usage may incur charges under your OpenAI account.
