# OpenCode VTuber Commentary Plugin

Watches your OpenCode sessions and has your Open-LLM-VTuber character speak sassy, witty summaries of what just happened.

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Install the plugin bridge into OpenCode:

```bash
python3 install.py
```

3. Start Open-LLM-VTuber and open the frontend.

4. Start an OpenCode session - the VTuber will comment when the session goes idle.

## Configuration

Edit `config.yaml` to customize:

- **vtuber** - Server URL and TTS endpoint
- **summary_llm** - Model (optional), timeout, and OpenCode binary used for summary generation
- **personality** - System prompt and tone for commentary
- **log** - Event log path, max events, minimum events before summarizing

## Uninstall

```bash
python3 install.py --uninstall
```

## How It Works

1. OpenCode plugin hooks capture `tool.execute.after` and `chat.message` events
2. Events are appended to a rolling JSONL log file
3. When `session.idle` fires, the pipeline calls `opencode run` for a witty summary
4. The summary is sent to Open-LLM-VTuber's broadcast TTS WebSocket endpoint so connected frontend avatars play it
