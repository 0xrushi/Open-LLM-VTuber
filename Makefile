.PHONY: all start sync install redis-up worker worker-obsidian workers status cleanup-twitter-social-links twitter-social-links-status run-scroll-script-in-container

DISCORD_POSTGRES_URL ?= postgres://discord:discord@localhost:5432/discord_ingestion
CONTAINER_NAME ?=
SCROLL_SCRIPT_PATH ?=
PYTHON_IN_CONTAINER ?= python

start:
	@echo ">> Building frontend..."
	@cd Open-LLM-VTuber-Web && npm install && npm run build:web
	@echo ">> Starting server..."
	uv run run_server.py

all:
	@echo ">> Starting Redis (if needed)..."
	@$(MAKE) redis-up
	@echo ">> Starting backend server..."
	@$(MAKE) start

sync:
	@echo ">> Syncing dependencies..."
	uv sync

install: sync

redis-up:
	@echo ">> Checking Redis on localhost:6379..."
	@redis-cli -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1 || (echo ">> Redis not running; starting redis-server..." && redis-server --daemonize yes)
	@redis-cli -h 127.0.0.1 -p 6379 ping

worker:
	PYTHONPATH=$(shell pwd)/src uv run python -m open_llm_vtuber.obsidian_mcp.worker

worker-obsidian:
	PYTHONPATH=$(shell pwd)/src uv run python -m open_llm_vtuber.obsidian_mcp.worker

workers:
	@echo ">> Start these in separate terminals:"
	@echo "   make worker-obsidian"

status:
	@echo ">> Redis:"
	@redis-cli -h 127.0.0.1 -p 6379 ping || true
	@echo ">> Infra endpoints:"
	@curl -sS http://localhost:12393/api/infra/redis-health || true
	@echo
	@curl -sS http://localhost:12393/api/infra/workers-health || true
	@echo

cleanup-twitter-social-links:
	@echo ">> Deleting Twitter/X pending+failed rows from social_links..."
	@DISCORD_POSTGRES_URL="$(DISCORD_POSTGRES_URL)" uv run python scripts/cleanup_twitter_social_links.py

twitter-social-links-status:
	@echo ">> Twitter/X social_links status summary..."
	@DISCORD_POSTGRES_URL="$(DISCORD_POSTGRES_URL)" uv run python scripts/twitter_social_links_status.py

run-scroll-script-in-container:
	@if [ -z "$(CONTAINER_NAME)" ]; then echo "ERROR: set CONTAINER_NAME=<docker container>"; exit 1; fi
	@if [ -z "$(SCROLL_SCRIPT_PATH)" ]; then echo "ERROR: set SCROLL_SCRIPT_PATH=<path inside container>"; exit 1; fi
	@echo ">> Running scroll script in container $(CONTAINER_NAME): $(SCROLL_SCRIPT_PATH)"
	@docker exec "$(CONTAINER_NAME)" $(PYTHON_IN_CONTAINER) "$(SCROLL_SCRIPT_PATH)"
