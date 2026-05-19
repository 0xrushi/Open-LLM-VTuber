# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open-LLM-VTuber is a voice-interactive AI companion with Live2D avatar support that runs completely offline. It's a cross-platform Python application supporting real-time voice conversations, visual perception, and Live2D character animations. The project features modular architecture for LLM, ASR (Automatic Speech Recognition), TTS (Text-to-Speech), and other components.

## Essential Commands

### Development Setup
- **Install dependencies**: `uv sync` (uses uv package manager)
- **Run server**: `uv run run_server.py`
- **Run with verbose logging**: `uv run run_server.py --verbose`
- **Update project**: `uv run upgrade.py`

### Code Quality
- **Lint code**: `ruff check .`
- **Format code**: `ruff format .`
- **Run pre-commit hooks**: `pre-commit run --all-files`

### Server Configuration
- **Main config file**: `conf.yaml` (user configuration)
- **Default configs**: `config_templates/conf.default.yaml` and `config_templates/conf.ZH.default.yaml`
- **Character configs**: `characters/` directory (YAML files)

## Architecture Overview

### Core Components

**WebSocket Server** (`src/open_llm_vtuber/server.py`):
- FastAPI-based server handling WebSocket connections
- Serves frontend, Live2D models, and static assets
- Supports both main client and proxy WebSocket endpoints

**Service Context** (`src/open_llm_vtuber/service_context.py`):
- Central dependency injection container
- Manages all engines (LLM, ASR, TTS, VAD, etc.)
- Each WebSocket connection gets its own service context instance

**WebSocket Handler** (`src/open_llm_vtuber/websocket_handler.py`):
- Routes WebSocket messages to appropriate handlers
- Manages client connections, groups, and conversation state
- Handles audio data, conversation triggers, and Live2D interactions

### Modular Engine System

The project uses a factory pattern for all AI engines:

**Agent System** (`src/open_llm_vtuber/agent/`):
- `agent_factory.py` - Factory for creating different agent types
- `agents/` - Various agent implementations (basic_memory, hume_ai, letta, mem0)
- `stateless_llm/` - Stateless LLM implementations (Claude, OpenAI, Ollama, etc.)

**ASR Engines** (`src/open_llm_vtuber/asr/`):
- Support for multiple ASR backends: Sherpa-ONNX, FunASR, Faster-Whisper, OpenAI Whisper, etc.
- Factory pattern for engine selection based on configuration

**TTS Engines** (`src/open_llm_vtuber/tts/`):
- Multiple TTS options: Azure TTS, Edge TTS, MeloTTS, CosyVoice, GPT-SoVITS, etc.
- Configurable voice cloning and multi-language support

**VAD (Voice Activity Detection)** (`src/open_llm_vtuber/vad/`):
- Silero VAD for detecting speech activity
- Essential for voice interruption without feedback loops

### Configuration Management

**Config System** (`src/open_llm_vtuber/config_manager/`):
- Type-safe configuration classes for each component
- Automatic validation and loading from YAML files
- Support for multiple character configurations and config switching

### Conversation System

**Conversation Handling** (`src/open_llm_vtuber/conversations/`):
- `conversation_handler.py` - Main conversation orchestration
- `single_conversation.py` - Individual user conversations
- `group_conversation.py` - Multi-user group conversations
- `tts_manager.py` - Audio streaming and TTS management

### MCP (Model Context Protocol) Integration

**MCP System** (`src/open_llm_vtuber/mcpp/`):
- Tool execution and server registry
- JSON detection and parameter extraction
- Integration with various MCP servers for extended functionality

## Key Development Patterns

### Error Handling
The codebase uses the missing `_cleanup_failed_connection` method pattern - when implementing new WebSocket handlers, ensure proper cleanup methods are implemented.

### Live2D Integration
- Models stored in `live2d-models/` directory
- Each model has its own `.model3.json` configuration
- Expression and motion control through WebSocket messages

### Audio Processing
- Real-time audio streaming through WebSocket
- Voice interruption support without headphones
- Multi-format audio support with proper codec handling

### Multi-language Support
- Character configurations support multiple languages
- TTS translation capabilities (speak in different language than input)
- I18n system for UI elements

## Important File Locations

- **Entry point**: `run_server.py`
- **Main server**: `src/open_llm_vtuber/server.py`
- **WebSocket routing**: `src/open_llm_vtuber/routes.py`
- **Configuration**: `conf.yaml` (user), `config_templates/` (defaults)
- **Frontend**: `frontend/` (Git submodule)
- **Live2D models**: `live2d-models/`
- **Character definitions**: `characters/`
- **Chat history**: `chat_history/`
- **Cache**: `cache/` (audio files, temporary data)
- **MCP servers config**: `mcp_servers.json` (tool server definitions and credentials)
- **Model registry**: `model_dict.json` (maps model names to URLs, renderer type, camera, scene)
- **Profile selector UI**: `src/open_llm_vtuber/static/profiles.html` (standalone character picker page)

## Profile Selection System

A standalone profile selector is served at `/profiles`. It shows rich cards per character (3D VRM preview, LLM/TTS badges, persona snippet) and redirects to the main app with the selected config pre-loaded.

**Flow:**
1. User visits `/profiles`, clicks a card
2. Browser POSTs to `/api/select-profile?config=<filename>` (server stores selection keyed by client IP with 30s TTL in `_pending_profile_store` in `routes.py`)
3. Browser redirects to `/`
4. On WebSocket connect, `websocket_handler.py:_get_pending_config()` reads the store and calls `service_context.apply_config_file()` before `_send_initial_messages` — so the client receives exactly one `set-model-and-conf` message with the correct character

**Key files:**
- `src/open_llm_vtuber/routes.py` — `init_profile_routes()`, `_pending_profile_store`
- `src/open_llm_vtuber/service_context.py` — `apply_config_file()` (silent config loader)
- `src/open_llm_vtuber/websocket_handler.py` — `_get_pending_config()` hook in `handle_new_connection`
- `src/open_llm_vtuber/config_manager/utils.py` — `scan_config_alts_directory_rich()` (reads all character YAMLs + model_dict.json to build profile metadata for the API)

## Character Configs (`characters/`)

Each YAML deep-merges over `conf.yaml`. Minimal fields needed: `conf_name`, `conf_uid`, `live2d_model_name`, `character_name`. Add `persona_prompt` under `character_config` to give the character its own personality — without it the character inherits the base conf's persona.

Current characters and their personas:
- `Nami.yaml` — warm, playful girlfriend; cozy interests
- `Hugo.yaml` — calm, dry-witted intellectual friend; debates and challenges
- `Yidhari.yaml` — fierce, blunt, intensely loyal warrior-type
- `characters/*.yaml` (GLB models) — see `model_dict.json` for renderer/scene config

All personas use the same output format: one `[emotion]` tag + one `[vocal]` tag prefix per reply.

## Obsidian MCP Integration

The Obsidian MCP server provides notes, todos, and calendar access via the local Obsidian vault. Chat LLM stays as `openai_compatible_llm`; Obsidian tools are only invoked when the user explicitly asks to search, create, schedule, or manage notes/tasks.

**Vault:** `/Users/bread/Documents/subsidian/453792`
**Embeddings:** `nomic-embed-text-v1.5` at `http://192.168.1.166:8084/v1`
**RAG index:** `~/.cache/obsidian_mcp_rag/` (ChromaDB, auto-rebuilt when vault changes)

**Config (`conf.yaml`):**
- `use_mcpp: True`
- `mcp_enabled_servers: ['obsidian']`
- `guidance_tool_router_enabled: True`
- `guidance_tool_router_target_servers: ['obsidian']`

**Routing logic (`src/open_llm_vtuber/agent/agents/basic_memory_agent.py`):**
- `_categorize_guidance_tools()` — buckets tools into `notes`, `todos`, `calendar` by keyword matching.
- `_run_guidance_router()` — lightweight LLM call that decides `mode: chat` vs `mode: tool_call` and selects a capability bucket. Schema enum: `["notes", "todos", "calendar"]`.
- `_GUIDANCE_ROUTER_SYSTEM_PROMPT` — instructs the router. Time/search are excluded; they are not in `guidance_tool_router_target_servers`.

**MCP server definition (`mcp_servers.json`):**
```json
"obsidian": {
  "command": "uv",
  "args": ["run", "--directory", "/Users/bread/Documents/Open-LLM-VTuber", "python", "-m", "open_llm_vtuber.obsidian_mcp.server"],
  "env": {
    "OBSIDIAN_VAULT_PATH": "/Users/bread/Documents/subsidian/453792",
    "EMBED_BASE_URL": "http://192.168.1.166:8084/v1",
    "EMBED_MODEL": "nomic-embed-text-v1.5"
  }
}
```

**MCP server source:** `src/open_llm_vtuber/obsidian_mcp/`
- `server.py` — FastMCP server with tools: `obsidian_search`, `obsidian_read`, `obsidian_create`, `obsidian_append`, `obsidian_tasks`, `obsidian_task_add`, `obsidian_daily_read`, `obsidian_daily_append`
- `rag.py` — `ObsidianRAG` class: indexes vault as ChromaDB embeddings, enables semantic search over 100k+ notes

**To force re-index the RAG:** Delete `~/.cache/obsidian_mcp_rag/` — it auto-rebuilds on next search.

**Requirements:** Obsidian app must be open for CLI-based tools (`obsidian_read`, `obsidian_tasks`, etc.) to work. `obsidian_search` (RAG) works without Obsidian open.

### Background Queue (Redis/RQ)

Slow Obsidian tool calls (especially `obsidian_search` with re-indexing) can be offloaded to a Redis/RQ background worker so the VTuber keeps chatting. The result is spoken aloud when the job completes (same "btw" injection path as the old OpenClaw async system).

**Enable:** `obsidian_async_enabled: True` in `conf.yaml` under `basic_memory_agent`.

**Start services:**
```bash
redis-server                                          # terminal 1 — Redis
uv run python -m open_llm_vtuber.obsidian_mcp.worker  # terminal 2 — RQ worker
uv run run_server.py --verbose                        # terminal 3 — VTuber server
```

**Key source files:**
- `src/open_llm_vtuber/obsidian_mcp/tasks.py` — RQ-serializable job functions (no closures)
- `src/open_llm_vtuber/obsidian_mcp/queue.py` — `ObsidianJobQueue` wrapper (graceful fallback if Redis down)
- `src/open_llm_vtuber/obsidian_mcp/worker.py` — RQ worker entry point
- `src/open_llm_vtuber/mcpp/tool_executor.py` — `_run_obsidian_async_nonblocking`, `_poll_obsidian_job`

**Graceful fallback:** If Redis is unreachable, `ObsidianJobQueue.is_available()` returns False and the call runs synchronously — no crash, no config change needed.

**Tests:** `tests/test_obsidian_queue.py` — run with `/test-obsidian-queue`

## Development Guidelines

### Adding New Engines
1. Create interface in appropriate directory (e.g., `asr_interface.py`)
2. Implement concrete class following existing patterns
3. Add to factory class (e.g., `asr_factory.py`)
4. Update configuration classes in `config_manager/`
5. Add configuration options to default YAML files

### WebSocket Message Handling
1. Add message type to `MessageType` enum in `websocket_handler.py`
2. Create handler method following `_handle_*` pattern
3. Register in `_init_message_handlers()` dictionary
4. Ensure proper error handling and client response

### Configuration Changes
- Always update both default config templates
- Maintain backward compatibility when possible
- Use the upgrade system for breaking changes
- Validate configurations in respective config manager classes

## Testing and Quality Assurance

The project uses:
- **Ruff** for linting and formatting (configured in `pyproject.toml`)
- **Pre-commit hooks** for automated quality checks
- **GitHub Actions** for CI/CD (`.github/workflows/`)
- Manual testing through web interface and desktop client

## Package Management

Uses **uv** (modern Python package manager):
- Dependencies defined in `pyproject.toml`
- Lock file: `uv.lock`
- Generated requirements: `requirements.txt` (auto-generated)
- Optional dependencies for specific features (e.g., `bilibili` extra)