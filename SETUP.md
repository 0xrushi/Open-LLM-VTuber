# Local Setup & Running

## Before Starting — Required Setup

Before running the server you need to do **all four** of these things:

1. **Add a Live2D character model** → `live2d-models/`
2. **Add background images** → `backgrounds/`
3. **Edit the main config** → `conf.yaml`
4. **Edit MCP servers** → `mcp_servers.json`

---

## 1. Add a Live2D Character Model

Place your Live2D model folder inside `live2d-models/`. Each model must contain
a `.model3.json` file at its root.

```
live2d-models/
  my-character/
    my-character.model3.json
    my-character.moc3
    ...
```

Currently available models: `VT_Elf`, `mao_pro`, `maroon`, `shizuku`

Then set the model name in `conf.yaml`:
```yaml
character_config:
  live2d_model_name: 'my-character'  # folder name under live2d-models/
```

---

## 2. Add Background Images

Drop image files (`.jpg`, `.jpeg`, `.png`, `.webp`) into the `backgrounds/` directory.
They will be served automatically and appear as selectable backgrounds in the web UI.

Several backgrounds are already included — add your own alongside them.

---

## 3. Edit `conf.yaml`

This is the main configuration file. Key things to set:

| Section | What to configure |
|---|---|
| `system_config` | `host` (`0.0.0.0` for LAN access), `port` (default `12393`) |
| `character_config` | `character_name`, `live2d_model_name`, `persona_prompt` |
| `agent_config.basic_memory_agent` | `llm_provider` — which LLM backend to use |
| `llm_configs.openai_compatible_llm` | `base_url`, `model` — your LLM endpoint |
| `asr_config.asr_model` | Which speech recognition engine to use |
| `tts_config.tts_model` | Which TTS engine to use |
| `vad_config.vad_model` | Voice activity detection (`null` to disable) |

**LLM provider options** (set `llm_provider` to one of):
`openai_compatible_llm`, `ollama_llm`, `claude_llm`, `openai_llm`, `gemini_llm`,
`lmstudio_llm`, `deepseek_llm`, `groq_llm`, `mistral_llm`, `llama_cpp_llm`

**ASR model options** (set `asr_model` to one of):
`sherpa_onnx_asr` (default, offline), `faster_whisper`, `whisper`, `whisper_cpp`,
`fun_asr`, `groq_whisper_asr`, `azure_asr`

**TTS model options** (set `tts_model` to one of):
`chatterbox_tts`, `chatterbox_turbo_api_tts`, `edge_tts`, `openai_tts`,
`elevenlabs_tts`, `azure_tts`, `melo_tts`, `gpt_sovits_tts`, `fish_api_tts`,
`minimax_tts`, `sherpa_onnx_tts`, `bark_tts`, `pyttsx3_tts`, `coqui_tts`

See `config_templates/conf.default.yaml` for all available options with comments.

---

## 4. Edit `mcp_servers.json`

This file defines the MCP (Model Context Protocol) tool servers the AI can call.
Copy the example if you haven't already:

```bash
cp mcp_servers.example.json mcp_servers.json
```

Edit `mcp_servers.json` and configure the servers you want:

```json
{
  "mcp_servers": {
    "openclaw": {
      "command": "npx",
      "args": ["openclaw-mcp"],
      "env": {
        "OPENCLAW_URL": "http://<your-host>:18789",
        "OPENCLAW_GATEWAY_TOKEN": ""
      }
    },
    "time": {
      "command": "uvx",
      "args": ["mcp-server-time", "--local-timezone=America/New_York"]
    }
  }
}
```

Then enable specific servers in `conf.yaml` under `agent_config`:
```yaml
agent_settings:
  basic_memory_agent:
    use_mcpp: True
    mcp_enabled_servers: ['openclaw', 'time']
```

---

## Running the Server

### Manually

```bash
.venv/bin/python run_server.py
# or with verbose logging:
.venv/bin/python run_server.py --verbose
```

### As a systemd user service

The service file is at `open-llm-vtuber.service` and is installed at
`~/.config/systemd/user/open-llm-vtuber.service`.

Alternative service file (same behavior) is also available at
`run_with_nullclaw_gateway.service`.

This service starts both:
- `run_server.py` (Open-LLM-VTuber)
- `nullclaw gateway` on `0.0.0.0:5001`

You can override paths/host/port in the service with:
- `OPEN_LLM_VTUBER_DIR`
- `NULLCLAW_BIN`
- `NULLCLAW_HOST`
- `NULLCLAW_PORT`

```bash
# Start / stop
systemctl --user start open-llm-vtuber
systemctl --user stop open-llm-vtuber

# Enable / disable on login
systemctl --user enable open-llm-vtuber
systemctl --user disable open-llm-vtuber

# View logs
journalctl --user -u open-llm-vtuber -f
```

To start the service automatically at boot even without logging in:
```bash
sudo loginctl enable-linger $USER
```

After editing the service file, copy it and reload:
```bash
cp open-llm-vtuber.service ~/.config/systemd/user/
systemctl --user daemon-reload
```

If your LLM/gateway uses environment secrets, make sure systemd user services receive them:

```bash
systemctl --user import-environment GEMINI_API_KEY LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY
systemctl --user restart open-llm-vtuber
```

Or persist them in `~/.config/open-llm-vtuber.env` (loaded by the service).

---

## Character Config Files

Additional characters live in `characters/` as individual YAML files. Each overrides
the defaults from `conf.yaml`. Switch between them via the web UI or by setting
`conf_name` in `conf.yaml`.

Current characters: `en_nuke_debate.yaml`, `en_unhelpful_ai.yaml`, `zh_米粒.yaml`, `zh_翻译腔.yaml`

---

## Web UI

Once the server is running, open: `http://localhost:12393`

For LAN access set `host: '0.0.0.0'` in `conf.yaml` and open `http://<machine-ip>:12393`.
