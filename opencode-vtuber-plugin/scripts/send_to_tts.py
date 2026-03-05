#!/usr/bin/env python3
"""Sends text to the Open-LLM-VTuber TTS WebSocket endpoint."""

import asyncio
import json
from pathlib import Path

import websockets

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def load_config():
    import yaml

    with open(PLUGIN_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def send_text(text: str, config: dict | None = None) -> bool:
    if config is None:
        config = load_config()

    url = config["vtuber"]["server_url"] + config["vtuber"]["tts_endpoint"]
    timeout = config["vtuber"]["timeout_seconds"]

    try:
        async with websockets.connect(url, close_timeout=timeout) as ws:
            await ws.send(json.dumps({"text": text}))
            while True:
                response = json.loads(
                    await asyncio.wait_for(ws.recv(), timeout=timeout)
                )
                if response.get("status") == "complete":
                    return True
                if response.get("status") == "error":
                    return False
    except Exception:
        return False


def send_to_tts(text: str, config: dict | None = None) -> bool:
    return asyncio.run(send_text(text, config))


if __name__ == "__main__":
    import sys

    text = sys.argv[1] if len(sys.argv) > 1 else "Hello from the plugin!"
    success = send_to_tts(text)
    print(f"Sent: {success}")
