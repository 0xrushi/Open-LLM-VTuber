#!/usr/bin/env python3
"""Main orchestrator: read events -> generate summary -> send to TTS -> clear log."""

import signal
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR / "scripts"))


def timeout_handler(_signum, _frame):
    sys.exit(0)


def main():
    import yaml
    from generate_summary import generate_summary
    from send_to_tts import send_to_tts

    with open(PLUGIN_DIR / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    timeout = config["vtuber"]["timeout_seconds"]
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout)

    try:
        summary = generate_summary(config)
        if not summary:
            return

        send_to_tts(summary, config)

        log_path = Path(config["log"]["file"])
        if log_path.exists():
            log_path.write_text("", encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    main()
