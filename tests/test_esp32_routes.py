"""Unit tests for the ESP32 alert route — all mocked, no server needed."""

import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(text)


class TestEsp32RoutesCooldown(unittest.TestCase):
    """Cooldown logic in init_esp32_routes."""

    def setUp(self):
        import src.open_llm_vtuber.routes as routes_mod
        routes_mod._last_esp32_alert_time = 0.0

    def _make_ws_handler(self, client_uids=("client-1",)):
        ws_handler = MagicMock()
        ws_handler.client_connections = {uid: FakeWebSocket() for uid in client_uids}
        ws_handler.client_contexts = {uid: MagicMock() for uid in client_uids}
        ws_handler._handle_conversation_trigger = AsyncMock()
        return ws_handler

    def _call_endpoint(self, ws_handler):
        from src.open_llm_vtuber.routes import init_esp32_routes
        router = init_esp32_routes(ws_handler)
        # Get the endpoint function directly
        route = next(r for r in router.routes if getattr(r, "path", "") == "/api/esp32-alert")
        return _run(route.endpoint(MagicMock()))

    def test_first_call_triggers_clients(self):
        ws_handler = self._make_ws_handler(["c1", "c2"])
        response = self._call_endpoint(ws_handler)
        body = json.loads(response.body)
        self.assertEqual(body["triggered"], 2)
        self.assertFalse(body["skipped_cooldown"])

    def test_second_call_within_cooldown_is_skipped(self):
        import src.open_llm_vtuber.routes as routes_mod
        routes_mod._last_esp32_alert_time = time.time()  # set as if just triggered
        ws_handler = self._make_ws_handler(["c1"])
        response = self._call_endpoint(ws_handler)
        body = json.loads(response.body)
        self.assertEqual(body["triggered"], 0)
        self.assertTrue(body["skipped_cooldown"])
        self.assertIn("cooldown_remaining_s", body)

    def test_call_after_cooldown_triggers_again(self):
        import src.open_llm_vtuber.routes as routes_mod
        routes_mod._last_esp32_alert_time = time.time() - 61  # expired
        ws_handler = self._make_ws_handler(["c1"])
        response = self._call_endpoint(ws_handler)
        body = json.loads(response.body)
        self.assertEqual(body["triggered"], 1)
        self.assertFalse(body["skipped_cooldown"])

    def test_no_clients_returns_zero_triggered(self):
        ws_handler = self._make_ws_handler([])
        response = self._call_endpoint(ws_handler)
        body = json.loads(response.body)
        self.assertEqual(body["triggered"], 0)
        self.assertFalse(body["skipped_cooldown"])

    def test_trigger_calls_conversation_handler_for_each_client(self):
        ws_handler = self._make_ws_handler(["c1", "c2", "c3"])
        self._call_endpoint(ws_handler)
        # create_task is called per client — verify handler was set up to be called
        self.assertEqual(ws_handler._handle_conversation_trigger.call_count, 3)

    def test_trigger_uses_text_input_type(self):
        ws_handler = self._make_ws_handler(["c1"])
        self._call_endpoint(ws_handler)
        call_kwargs = ws_handler._handle_conversation_trigger.call_args_list[0][1]
        self.assertEqual(call_kwargs["data"]["type"], "text-input")
        self.assertIn("text", call_kwargs["data"])
        self.assertGreater(len(call_kwargs["data"]["text"]), 0)

    def test_missing_context_skips_client(self):
        ws_handler = self._make_ws_handler(["c1", "c2"])
        # Remove context for c2 — should only trigger c1
        del ws_handler.client_contexts["c2"]
        response = self._call_endpoint(ws_handler)
        body = json.loads(response.body)
        self.assertEqual(body["triggered"], 1)


class TestEsp32PromptContent(unittest.TestCase):
    """Verify the free-time prompt is set and meaningful."""

    def test_prompt_mentions_free_and_entertain(self):
        from src.open_llm_vtuber.routes import _ESP32_FREE_PROMPT
        self.assertIn("free", _ESP32_FREE_PROMPT.lower())
        # Should ask the character to entertain
        self.assertTrue(
            any(w in _ESP32_FREE_PROMPT.lower() for w in ["joke", "fun", "entertain", "interesting"])
        )

    def test_cooldown_is_60_seconds(self):
        from src.open_llm_vtuber.routes import _ESP32_COOLDOWN_SECONDS
        self.assertEqual(_ESP32_COOLDOWN_SECONDS, 60.0)


class TestEsp32ServerRegistration(unittest.TestCase):
    """Verify init_esp32_routes is imported and registered in server.py."""

    def test_init_esp32_routes_exported_from_routes(self):
        from src.open_llm_vtuber.routes import init_esp32_routes
        self.assertTrue(callable(init_esp32_routes))

    def test_init_esp32_routes_imported_in_server(self):
        import ast
        from pathlib import Path
        server_src = (Path(__file__).parent.parent / "src/open_llm_vtuber/server.py").read_text()
        tree = ast.parse(server_src)
        imported_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "routes" in node.module:
                imported_names.extend(alias.name for alias in node.names)
        self.assertIn("init_esp32_routes", imported_names)


if __name__ == "__main__":
    unittest.main()
