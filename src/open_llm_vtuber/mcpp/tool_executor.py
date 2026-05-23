import json
import os
import datetime
import asyncio
import re
from loguru import logger
from typing import (
    Dict,
    Any,
    List,
    Literal,
    Union,
    AsyncIterator,
)

from .types import ToolCallObject
from .mcp_client import MCPClient
from .tool_manager import ToolManager
from .background_search_pipeline import BackgroundSearchPipeline


class ToolExecutor:
    def __init__(
        self,
        mcp_client: MCPClient,
        tool_manager: ToolManager,
        obsidian_async_enabled: bool = False,
        web_search_async_enabled: bool = True,
    ):
        self._mcp_client = mcp_client
        self._tool_manager = tool_manager
        self._obsidian_async_enabled = obsidian_async_enabled
        self._background_tasks: set[asyncio.Task] = set()
        self.suppress_tts_this_turn: bool = False

        if obsidian_async_enabled:
            from open_llm_vtuber.obsidian_mcp.queue import ObsidianJobQueue

            self._obsidian_queue = ObsidianJobQueue()
            if not self._obsidian_queue.is_available():
                logger.warning(
                    "obsidian_async_enabled=True but Redis is not reachable. "
                    "Obsidian calls will run synchronously."
                )
        else:
            self._obsidian_queue = None

        if web_search_async_enabled:
            from open_llm_vtuber.skills.queue import WebSearchJobQueue

            self._web_search_queue = WebSearchJobQueue()
            if not self._web_search_queue.is_available():
                logger.warning(
                    "web_search_async_enabled=True but Redis is not reachable. "
                    "Web search calls will run synchronously."
                )
        else:
            self._web_search_queue = None

    def _extract_text_from_content_items(
        self, content_items: List[Dict[str, Any]]
    ) -> str:
        """Extract first text payload from MCP content items."""
        for item in content_items:
            if item.get("type") == "text":
                return item.get("text", "")
        return ""

    async def _send_ws_event(self, payload: Dict[str, Any]) -> None:
        """Best-effort websocket push using MCP client callback."""
        send_text = getattr(self._mcp_client, "_send_text", None)
        if not send_text:
            return
        try:
            await send_text(json.dumps(payload))
        except Exception as exc:
            logger.error(f"Failed to send websocket event: {exc}")

    async def _speak_background_result(self, text: str) -> None:
        """Best-effort background TTS callback for async tool completion."""
        speak_cb = getattr(self._mcp_client, "_background_result_handler", None)
        if not speak_cb:
            logger.warning("_speak_background_result: no _background_result_handler set on MCP client — result not spoken")
            return
        try:
            await speak_cb(text)
        except Exception as exc:
            logger.error(f"Failed background result speech callback: {exc}")

    @staticmethod
    def _sanitize_background_result(tool_name: str, text: str) -> str:
        """Strip tool-internal prompt scaffolding from user-facing background output."""
        cleaned = (text or "").strip()
        if not cleaned:
            return cleaned
        if tool_name in {"discord_search", "twitter_search"}:
            marker = "\n---\nINSTRUCTION:"
            idx = cleaned.find(marker)
            if idx != -1:
                cleaned = cleaned[:idx].rstrip()
        return cleaned

    @staticmethod
    def _format_background_result(tool_name: str, text: str) -> str:
        """Produce a concise, user-facing completion message for async social searches."""
        cleaned = (text or "").strip()
        if not cleaned:
            return cleaned
        if tool_name == "pi_web_search":
            # For web search, return the raw result but ensure it's reasonable length for TTS
            # Truncate to avoid TTS timeouts
            return cleaned[:1500] if len(cleaned) > 1500 else cleaned
        pipeline = BackgroundSearchPipeline(tool_name=tool_name, raw_text=cleaned)
        result = pipeline.run()
        if result.evidence:
            return f"{result.answer} Recent mentions: {' | '.join(result.evidence)}"
        return result.answer

    async def _poll_obsidian_job(
        self,
        job_id: str,
        origin_tool_name: str,
        origin_tool_id: str,
        poll_interval_sec: float = 2.0,
        timeout_sec: float = 120.0,
    ) -> None:
        """Poll an RQ job for an Obsidian tool call and deliver the result via TTS."""
        if self._obsidian_queue is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout_sec

        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(poll_interval_sec)
            try:
                status, result = self._obsidian_queue.get_result(job_id)
            except Exception as exc:
                logger.error(f"Error polling Obsidian job {job_id}: {exc}")
                continue

            if status == "finished":
                result_text = self._sanitize_background_result(
                    origin_tool_name, (result or "").strip()
                )
                result_text = self._format_background_result(origin_tool_name, result_text)
                await self._send_ws_event(
                    {
                        "type": "tool_call_status",
                        "tool_id": origin_tool_id,
                        "tool_name": origin_tool_name,
                        "status": "completed",
                        "content": result_text or f"Obsidian job {job_id} completed.",
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
                    }
                )
                if result_text:
                    speak_task = asyncio.create_task(
                        self._speak_background_result(result_text)
                    )
                    self._background_tasks.add(speak_task)
                    speak_task.add_done_callback(self._background_tasks.discard)
                self._obsidian_queue.cleanup(job_id)
                return

            if status == "failed":
                error_text = (result or f"Obsidian job {job_id} failed.").strip()
                await self._send_ws_event(
                    {
                        "type": "tool_call_status",
                        "tool_id": origin_tool_id,
                        "tool_name": origin_tool_name,
                        "status": "error",
                        "content": error_text,
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
                    }
                )
                self._obsidian_queue.cleanup(job_id)
                return

        # Timeout
        await self._send_ws_event(
            {
                "type": "tool_call_status",
                "tool_id": origin_tool_id,
                "tool_name": origin_tool_name,
                "status": "error",
                "content": f"Obsidian job {job_id} timed out after {int(timeout_sec)}s.",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
            }
        )
        self._obsidian_queue.cleanup(job_id)

    async def _run_direct_tool(
        self,
        tool_name: str,
        tool_id: str,
        tool_input: Any,
        background: bool = False,
    ) -> tuple[bool, str, Dict[str, Any], List[Dict[str, Any]]]:
        """Execute a direct-call Python tool (no MCP server).

        Direct tools are registered via ToolManager.register_direct_tool()
        and have ``related_server="direct"``.

        When background=True, the tool runs in an asyncio.Task and returns
        an immediately-yielding placeholder so the conversation loop doesn't block.
        """
        func = self._tool_manager.get_direct_tool(tool_name)
        if func is None:
            logger.error(f"Direct tool '{tool_name}' not found in ToolManager.")
            return (
                True,
                f"Error: Direct tool '{tool_name}' is not available.",
                {},
                [{"type": "error", "text": f"Tool '{tool_name}' not found."}],
            )

        if background:
            # Run in background — return placeholder so the caller can yield
            # a status update and continue without blocking on the tool.
            async def _worker() -> tuple[bool, str, Dict[str, Any], List[Dict[str, Any]]]:
                logger.info(f"[BG_TOOL_WORKER] Starting background execution of {tool_name}")
                try:
                    result = await func(**(tool_input if isinstance(tool_input, dict) else {}))
                    text_content = str(result)
                    logger.info(f"[BG_TOOL_WORKER] {tool_name} completed successfully (content_len={len(text_content) if text_content else 0})")
                    return (
                        False,
                        text_content,
                        {},
                        [{"type": "text", "text": text_content}],
                    )
                except Exception as exc:
                    logger.exception(f"[BG_TOOL_WORKER] Error executing direct tool '{tool_name}': {exc}")
                    text_content = f"Error executing direct tool '{tool_name}': {exc}"
                    return (
                        True,
                        text_content,
                        {},
                        [{"type": "error", "text": text_content}],
                    )

            task = asyncio.create_task(_worker())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

            # Return a placeholder that signals the tool is running in background
            queued_text = f"{tool_name.replace('_', ' ').title()} queued in background."
            return (
                False,
                queued_text,
                {"_bg_task": task, "_tool_name": tool_name, "_tool_id": tool_id},
                [{"type": "text", "text": queued_text}],
            )

        try:
            result = await func(**(tool_input if isinstance(tool_input, dict) else {}))
            text_content = str(result)
            logger.info(f"Direct tool '{tool_name}' executed successfully.")
            return (
                False,
                text_content,
                {},
                [{"type": "text", "text": text_content}],
            )
        except Exception as exc:
            logger.exception(f"Error executing direct tool '{tool_name}': {exc}")
            text_content = f"Error executing direct tool '{tool_name}': {exc}"
            return (
                True,
                text_content,
                {},
                [{"type": "error", "text": text_content}],
            )

    async def _run_direct_tool_async_nonblocking(
        self,
        tool_name: str,
        tool_id: str,
        tool_input: Any,
        queued_text: str,
    ) -> tuple[bool, str, Dict[str, Any], List[Dict[str, Any]]]:
        """Run a direct tool in the background and return immediately."""

        async def _worker() -> None:
            logger.info(f"[BG_TOOL_WORKER] Starting background execution of {tool_name}")
            is_error, text_content, _, _ = await self._run_direct_tool(
                tool_name, tool_id, tool_input
            )
            logger.info(f"[BG_TOOL_WORKER] {tool_name} completed (is_error={is_error}, content_len={len(text_content) if text_content else 0})")
            status = "error" if is_error else "completed"
            payload = {
                "type": "tool_call_status",
                "tool_id": tool_id,
                "tool_name": tool_name,
                "status": status,
                "content": text_content,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                + "Z",
            }
            await self._send_ws_event(payload)
            logger.info(f"[BG_TOOL_WORKER] Sent tool status event for {tool_name}")
            if not is_error and text_content:
                formatted_result = self._format_background_result(tool_name, text_content)
                logger.info(f"[BG_TOOL_WORKER] Formatted result for {tool_name} (len={len(formatted_result) if formatted_result else 0})")
                if formatted_result:
                    logger.info(f"[BG_TOOL_WORKER] Speaking background result for {tool_name}")
                    await self._speak_background_result(formatted_result)
                    logger.info(f"[BG_TOOL_WORKER] Background TTS complete for {tool_name}")
                else:
                    logger.info(f"[BG_TOOL_WORKER] Formatted result was empty for {tool_name}")

        task = asyncio.create_task(_worker())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return (
            False,
            queued_text,
            {},
            [{"type": "text", "text": queued_text}],
        )

    async def _poll_web_search_job(
        self,
        job_id: str,
        origin_tool_id: str,
        poll_interval_sec: float = 3.0,
        timeout_sec: float = 300.0,
    ) -> None:
        """Poll a Redis/RQ web search job and deliver the result via TTS when done."""
        if self._web_search_queue is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout_sec

        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(poll_interval_sec)
            try:
                status, result = self._web_search_queue.get_result(job_id)
            except Exception as exc:
                logger.error(f"Error polling web search job {job_id}: {exc}")
                continue

            if status == "finished":
                result_text = (result or "").strip()
                if result_text and len(result_text) > 1500:
                    result_text = result_text[:1500].rstrip() + " ..."
                await self._send_ws_event(
                    {
                        "type": "tool_call_status",
                        "tool_id": origin_tool_id,
                        "tool_name": "pi_web_search",
                        "status": "completed",
                        "content": result_text or f"Web search job {job_id} completed.",
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
                    }
                )
                if result_text:
                    speak_task = asyncio.create_task(
                        self._speak_background_result(result_text)
                    )
                    self._background_tasks.add(speak_task)
                    speak_task.add_done_callback(self._background_tasks.discard)
                self._web_search_queue.cleanup(job_id)
                return

            if status == "failed":
                error_text = (result or f"Web search job {job_id} failed.").strip()
                await self._send_ws_event(
                    {
                        "type": "tool_call_status",
                        "tool_id": origin_tool_id,
                        "tool_name": "pi_web_search",
                        "status": "error",
                        "content": error_text,
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
                    }
                )
                self._web_search_queue.cleanup(job_id)
                return

        await self._send_ws_event(
            {
                "type": "tool_call_status",
                "tool_id": origin_tool_id,
                "tool_name": "pi_web_search",
                "status": "error",
                "content": f"Web search job {job_id} timed out after {int(timeout_sec)}s.",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
            }
        )
        self._web_search_queue.cleanup(job_id)

    async def _run_web_search_nonblocking(
        self,
        tool_name: str,
        tool_id: str,
        tool_input: Any,
    ) -> tuple[bool, str, dict, list]:
        """Enqueue a pi_web_search job to Redis/RQ and return immediately.

        Falls back to synchronous execution if Redis is unavailable.
        """
        import os as _os
        if self._web_search_queue is None or not self._web_search_queue.is_available():
            logger.info("Web search queue unavailable, running sync.")
            return await self._run_direct_tool(tool_name, tool_id, tool_input)

        args = tool_input if isinstance(tool_input, dict) else {}
        query = str(args.get("query", "")).strip()
        max_results = int(args.get("max_results", 5))
        pi_bin = _os.environ.get("PI_WEB_SEARCH_BIN", "pi")
        skill_name = _os.environ.get("PI_WEB_SEARCH_SKILL", "browseros-pi")
        provider = _os.environ.get("PI_WEB_SEARCH_PROVIDER") or None
        model = _os.environ.get("PI_WEB_SEARCH_MODEL") or None

        if not query:
            return (True, "Error: query is required.", {}, [{"type": "error", "text": "query is required"}])

        try:
            job_id = self._web_search_queue.enqueue(query, max_results, pi_bin, skill_name, provider, model)
        except Exception as exc:
            logger.warning(f"Failed to enqueue web search job, running sync: {exc}")
            return await self._run_direct_tool(tool_name, tool_id, tool_input)

        poll_task = asyncio.create_task(
            self._poll_web_search_job(job_id=job_id, origin_tool_id=tool_id)
        )
        self._background_tasks.add(poll_task)
        poll_task.add_done_callback(self._background_tasks.discard)

        self.suppress_tts_this_turn = True
        queued_text = "Web search queued. Results will be spoken when ready."
        return (False, queued_text, {}, [{"type": "text", "text": queued_text}])

    async def _run_obsidian_async_nonblocking(
        self,
        tool_name: str,
        tool_id: str,
        tool_input: Any,
    ) -> tuple[bool, str, Dict[str, Any], List[Dict[str, Any]]]:
        """Enqueue an Obsidian tool call to Redis/RQ and return immediately.

        Falls back to synchronous execution if Redis is unavailable.
        """
        if self._obsidian_queue is None or not self._obsidian_queue.is_available():
            logger.info(f"Obsidian async unavailable for '{tool_name}', running sync.")
            return await self.run_single_tool(tool_name, tool_id, tool_input)

        vault_path = os.environ.get("OBSIDIAN_VAULT_PATH", "/Users/bread/Documents/subsidian/453792")
        embed_base_url = os.environ.get("EMBED_BASE_URL", "https://llm.emberfang.xyz/v1")
        embed_model = os.environ.get("EMBED_MODEL", "nomic-embed-text-v1.5")

        try:
            job_id = self._obsidian_queue.enqueue(
                tool_name,
                tool_input if isinstance(tool_input, dict) else {},
                vault_path,
                embed_base_url,
                embed_model,
            )
        except Exception as exc:
            logger.warning(f"Failed to enqueue Obsidian job, running sync: {exc}")
            return await self.run_single_tool(tool_name, tool_id, tool_input)

        poll_task = asyncio.create_task(
            self._poll_obsidian_job(
                job_id=job_id,
                origin_tool_name=tool_name,
                origin_tool_id=tool_id,
            )
        )
        self._background_tasks.add(poll_task)
        poll_task.add_done_callback(self._background_tasks.discard)

        if tool_name in {"discord_search", "discord_sync", "twitter_search", "twitter_sync"}:
            queued_text = (
                "I have asked my ZEUS AGENT to run that in the background. "
                "I will notify you when it is ready; until then we can continue chatting."
            )
        else:
            queued_text = "On it — checking your notes in the background. I'll let you know when it's ready."
        return (
            False,
            queued_text,
            {},
            [{"type": "text", "text": queued_text}],
        )

    async def _poll_openclaw_async_task(
        self,
        server_name: str,
        origin_tool_name: str,
        origin_tool_id: str,
        task_id: str,
        poll_interval_sec: float = 5.0,
        timeout_sec: float = 300.0,
    ) -> None:
        """Poll openclaw_task_status in background and push completion to UI."""
        deadline = asyncio.get_running_loop().time() + timeout_sec

        while asyncio.get_running_loop().time() < deadline:
            try:
                result = await self._mcp_client.call_tool(
                    server_name=server_name,
                    tool_name="openclaw_task_status",
                    tool_args={"task_id": task_id},
                )
                content_items = result.get("content_items", [])
                text_payload = self._extract_text_from_content_items(content_items)
                if not text_payload:
                    await asyncio.sleep(poll_interval_sec)
                    continue

                try:
                    status_obj = json.loads(text_payload)
                except json.JSONDecodeError:
                    logger.warning(
                        f"openclaw_task_status returned non-JSON text: {text_payload[:200]}"
                    )
                    await asyncio.sleep(poll_interval_sec)
                    continue

                status = str(status_obj.get("status", "")).lower()

                if status == "completed":
                    result_text = str(status_obj.get("result", "")).strip()
                    await self._send_ws_event(
                        {
                            "type": "tool_call_status",
                            "tool_id": origin_tool_id,
                            "tool_name": origin_tool_name,
                            "status": "completed",
                            "content": result_text
                            if result_text
                            else f"OpenClaw async task {task_id} completed.",
                            "timestamp": datetime.datetime.now(
                                datetime.timezone.utc
                            ).isoformat()
                            + "Z",
                        }
                    )
                    if result_text:
                        speak_task = asyncio.create_task(
                            self._speak_background_result(result_text)
                        )
                        self._background_tasks.add(speak_task)
                        speak_task.add_done_callback(self._background_tasks.discard)
                    return

                if status in {"failed", "cancelled"}:
                    error_text = str(
                        status_obj.get("error", f"Task ended with status '{status}'")
                    )
                    await self._send_ws_event(
                        {
                            "type": "tool_call_status",
                            "tool_id": origin_tool_id,
                            "tool_name": origin_tool_name,
                            "status": "error",
                            "content": f"OpenClaw async task {task_id}: {error_text}",
                            "timestamp": datetime.datetime.now(
                                datetime.timezone.utc
                            ).isoformat()
                            + "Z",
                        }
                    )
                    return

            except Exception as exc:
                logger.error(f"Error polling OpenClaw async task {task_id}: {exc}")

            await asyncio.sleep(poll_interval_sec)

        await self._send_ws_event(
            {
                "type": "tool_call_status",
                "tool_id": origin_tool_id,
                "tool_name": origin_tool_name,
                "status": "error",
                "content": f"OpenClaw async task {task_id} timed out after {int(timeout_sec)}s.",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                + "Z",
            }
        )

    async def _run_openclaw_chat_async_nonblocking(
        self,
        tool_name: str,
        tool_id: str,
        tool_input: Any,
    ) -> tuple[bool, str, Dict[str, Any], List[Dict[str, Any]]]:
        """Execute openclaw_chat asynchronously and return immediately."""
        tool_info = self._tool_manager.get_tool(tool_name)
        if not tool_info or not tool_info.related_server:
            return (
                True,
                f"Error: Tool '{tool_name}' has no configured server.",
                {},
                [{"type": "error", "text": f"Tool '{tool_name}' has no server."}],
            )

        message = ""
        if isinstance(tool_input, dict):
            message = str(tool_input.get("message", "")).strip()
        if not message:
            return (
                True,
                "Error: openclaw_chat requires a non-empty 'message'.",
                {},
                [{"type": "error", "text": "Missing message for openclaw_chat."}],
            )

        async_result = await self._mcp_client.call_tool(
            server_name=tool_info.related_server,
            tool_name="openclaw_chat_async",
            tool_args={"message": message},
        )
        content_items = async_result.get("content_items", [])
        text_payload = self._extract_text_from_content_items(content_items)
        if not text_payload:
            return (
                True,
                "Error: openclaw_chat_async returned empty response.",
                async_result.get("metadata", {}),
                [{"type": "error", "text": "openclaw_chat_async returned empty response."}],
            )

        try:
            parsed = json.loads(text_payload)
        except json.JSONDecodeError as exc:
            return (
                True,
                f"Error: Failed to parse openclaw_chat_async response: {text_payload}",
                async_result.get("metadata", {}),
                [{"type": "error", "text": f"Invalid async response: {exc}"}],
            )

        task_id = parsed.get("task_id")
        if not task_id:
            return (
                True,
                f"Error: openclaw_chat_async did not return task_id: {text_payload}",
                async_result.get("metadata", {}),
                [{"type": "error", "text": "Missing task_id from openclaw_chat_async."}],
            )

        poll_task = asyncio.create_task(
            self._poll_openclaw_async_task(
                server_name=tool_info.related_server,
                origin_tool_name=tool_name,
                origin_tool_id=tool_id,
                task_id=task_id,
            )
        )
        self._background_tasks.add(poll_task)
        poll_task.add_done_callback(self._background_tasks.discard)

        queued_text = (
            f"OpenClaw task queued (task_id={task_id}). "
            "Running in background; I will post the final result when it is ready."
        )
        return (
            False,
            queued_text,
            async_result.get("metadata", {}),
            [{"type": "text", "text": queued_text}],
        )

    def parse_tool_call(self, call: Union[Dict[str, Any], ToolCallObject]) -> tuple:
        """Parse tool call from different formats.

        Returns:
            tuple: (tool_name, tool_id, tool_input, is_error, result_content, parse_error)
        """
        tool_name: str = ""
        tool_id: str = ""
        tool_input: Any = None
        is_error: bool = False
        result_content: str | dict = ""
        parse_error: bool = False

        def _repair_json_args(raw: Any) -> Any:
            """Best-effort repair for truncated OpenAI tool arguments JSON."""
            if not isinstance(raw, str):
                return raw

            s = raw.strip()
            if not s:
                return {}

            # Fast path
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                pass

            # Common truncation: missing quote/brace at end of stream.
            fixed = s
            quote_count = sum(1 for i, ch in enumerate(fixed) if ch == '"' and (i == 0 or fixed[i - 1] != "\\"))
            if quote_count % 2 == 1:
                fixed += '"'

            open_braces = fixed.count("{")
            close_braces = fixed.count("}")
            if close_braces < open_braces:
                fixed += "}" * (open_braces - close_braces)

            open_brackets = fixed.count("[")
            close_brackets = fixed.count("]")
            if close_brackets < open_brackets:
                fixed += "]" * (open_brackets - close_brackets)

            try:
                repaired = json.loads(fixed)
                logger.warning(
                    f"Recovered malformed tool arguments JSON via repair. original={s!r} repaired={fixed!r}"
                )
                return repaired
            except json.JSONDecodeError:
                return None

        if isinstance(call, ToolCallObject):
            tool_name = call.function.name
            tool_id = call.id
            repaired = _repair_json_args(call.function.arguments)
            if repaired is None:
                logger.error(
                    f"Failed to decode OpenAI tool arguments for '{tool_name}'"
                )
                result_content = (
                    f"Error: Invalid arguments format for tool '{tool_name}'."
                )
                is_error = True
                parse_error = True
            else:
                tool_input = repaired
        elif isinstance(call, dict):
            tool_id = call.get("id")
            tool_name = call.get("name")
            tool_input = call.get("input", call.get("args"))

            if tool_input is None:
                logger.warning(
                    f"Empty input for tool '{tool_name}' (ID: {tool_id}). Using empty object."
                )
                tool_input = {}

            if not tool_id or not tool_name:
                logger.error(f"Invalid Dict tool call structure: {call}")
                result_content = "Error: Invalid tool call structure from LLM."
                is_error = True
                parse_error = True
        else:
            logger.error(f"Unsupported tool call type: {type(call)}")
            result_content = "Error: Unsupported tool call type."
            is_error = True
            parse_error = True

        return tool_name, tool_id, tool_input, is_error, result_content, parse_error

    def format_tool_result(
        self,
        caller_mode: Literal["Claude", "OpenAI", "Prompt"],
        tool_id: str,
        result_content: str,
        is_error: bool,
    ) -> Dict[str, Any] | None:
        """Format tool result for LLM API."""
        if caller_mode == "Claude":
            # Claude expects content as a list of blocks or a simple string
            # We will return a list if there are multiple items or non-text items
            if isinstance(result_content, list):
                # Already formatted as list of blocks
                content_to_send = result_content
            elif isinstance(result_content, str) and result_content:
                # Simple text result
                content_to_send = result_content
            elif not result_content and is_error:
                # Error case, send error message as string
                content_to_send = "Error occurred during tool execution."
            else:
                # Fallback for empty or unexpected content
                content_to_send = ""

            return {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": content_to_send,
                "is_error": is_error,
            }
        elif caller_mode == "OpenAI":
            # OpenAI expects content as a string
            return {
                "role": "tool",
                "tool_call_id": tool_id,
                "content": str(result_content),
            }
        elif caller_mode == "Prompt":
            # Prompt mode also expects a string content for now
            return {
                "tool_id": tool_id,
                "content": str(result_content),
                "is_error": is_error,
            }
        return None

    def process_tool_from_prompt_json(
        self, data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process tool data from JSON in prompt mode."""
        parsed_tools = []
        for item in data:
            server = item.get("mcp_server")
            tool_name = item.get("tool")
            arguments_str = item.get("arguments")
            if all([server, tool_name, arguments_str]):
                try:
                    args_dict = json.loads(arguments_str)
                    parsed_tools.append(
                        {
                            "name": tool_name,
                            "server": server,
                            "args": args_dict,
                            "id": f"prompt_tool_{len(parsed_tools)}",
                        }
                    )
                    logger.info(f"Parsed tool call from prompt JSON: {tool_name}")
                except json.JSONDecodeError:
                    logger.error(
                        "Failed to decode arguments JSON in prompt mode tool call"
                    )
                except Exception as e:
                    logger.error(f"Error processing prompt mode tool dict: {e}")
            else:
                logger.warning("Skipping invalid tool structure in prompt mode JSON")
        return parsed_tools

    async def execute_tools(
        self,
        tool_calls: Union[List[Dict[str, Any]], List[ToolCallObject]],
        caller_mode: Literal["Claude", "OpenAI", "Prompt"],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Execute tools and yield status updates."""
        tool_results_for_llm = []

        logger.info(f"Executing {len(tool_calls)} tool(s) for {caller_mode} caller.")
        for call in tool_calls:
            (
                tool_name,
                tool_id,
                tool_input,
                is_error,
                result_content,
                parse_error,
            ) = self.parse_tool_call(call)

            logger.info(f"Executing tool: {call}")

            if parse_error:
                logger.warning(
                    f"Skipping tool call due to parsing error: {result_content}"
                )
                status_update = {
                    "type": "tool_call_status",
                    "tool_id": tool_id
                    or f"parse_error_{datetime.datetime.now(datetime.timezone.utc).isoformat()}",
                    "tool_name": tool_name or "Unknown Tool",
                    "status": "error",
                    "content": result_content,
                    "timestamp": datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat()
                    + "Z",
                }
                yield status_update
                # Even on parse error, we might need to format a result for the LLM
                # Use dummy values or the error message
                formatted_result = self.format_tool_result(
                    caller_mode,
                    tool_id
                    or f"parse_error_{datetime.datetime.now(datetime.timezone.utc).isoformat()}",
                    result_content,
                    True,  # is_error
                )
                if formatted_result:
                    tool_results_for_llm.append(formatted_result)
                continue  # Skip execution logic for this call

            # Yield 'running' status before execution
            yield {
                "type": "tool_call_status",
                "tool_id": tool_id,
                "tool_name": tool_name,
                "status": "running",
                "content": f"Input: {json.dumps(tool_input)}",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                + "Z",
            }

            # Execute the tool
            tool_info = self._tool_manager.get_tool(tool_name)
            related_server = str(getattr(tool_info, "related_server", "")).lower() if tool_info else ""
            if (
                tool_name == "openclaw_chat"
                and tool_info
                and related_server == "openclaw"
            ):
                (
                    is_error,
                    text_content,
                    metadata,
                    content_items,
                ) = await self._run_openclaw_chat_async_nonblocking(
                    tool_name, tool_id, tool_input
                )
            elif (
                self._obsidian_async_enabled
                and tool_info
                and related_server == "obsidian"
            ):
                (
                    is_error,
                    text_content,
                    metadata,
                    content_items,
                ) = await self._run_obsidian_async_nonblocking(
                    tool_name, tool_id, tool_input
                )
            elif related_server == "direct" and tool_info and tool_name == "pi_web_search":
                (
                    is_error,
                    text_content,
                    metadata,
                    content_items,
                ) = await self._run_web_search_nonblocking(
                    tool_name=tool_name,
                    tool_id=tool_id,
                    tool_input=tool_input,
                )
            elif related_server == "direct" and tool_info:
                # Run all direct tools (pi_obsidian_agent, pi_web_search, etc.)
                # in the background so the conversation loop doesn't block.
                (
                    is_error,
                    text_content,
                    metadata,
                    content_items,
                ) = await self._run_direct_tool(
                    tool_name, tool_id, tool_input, background=True
                )
            else:
                (
                    is_error,
                    text_content,
                    metadata,
                    content_items,
                ) = await self.run_single_tool(tool_name, tool_id, tool_input)

            # Determine content for status update and LLM result format
            status_content = text_content  # Default to text content
            llm_formatted_content = text_content  # Default to text content for LLM

            if content_items:
                image_items = [
                    item for item in content_items if item.get("type") == "image"
                ]
                if image_items:
                    num_images = len(image_items)
                    status_content = (
                        f"{text_content}\n[Tool returned {num_images} image(s)]".strip()
                    )

                    if caller_mode == "Claude":
                        # Format for Claude: list of blocks
                        claude_blocks = []
                        if text_content:
                            claude_blocks.append({"type": "text", "text": text_content})
                        for item in content_items:
                            if (
                                item.get("type") == "image"
                                and "data" in item
                                and "mimeType" in item
                            ):
                                claude_blocks.append(
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": item["mimeType"],
                                            "data": item["data"],
                                        },
                                    }
                                )
                            # Add other non-text types here
                        llm_formatted_content = (
                            claude_blocks if claude_blocks else ""
                        )  # Use blocks or empty string
                    elif caller_mode in ["OpenAI", "Prompt"]:
                        llm_formatted_content = status_content

            # Prepare and yield tool call status update
            status_update = {
                "type": "tool_call_status",
                "tool_id": tool_id,
                "tool_name": tool_name,
                "status": "error" if is_error else "completed",
                "content": status_content
                if not is_error
                else f"Error: {text_content}",  # Use descriptive content or error message
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                + "Z",
            }

            # For stagehand_navigate tool, include browser view links if available
            if tool_name == "stagehand_navigate" and not is_error:
                live_view_data = metadata.get("liveViewData", {})
                if live_view_data:
                    logger.info(
                        f"Found live view data for stagehand_navigate: {live_view_data}"
                    )
                    status_update["browser_view"] = live_view_data

            yield status_update

            # Format result for LLM and add to list
            formatted_result = self.format_tool_result(
                caller_mode, tool_id, llm_formatted_content, is_error
            )
            if formatted_result:
                tool_results_for_llm.append(formatted_result)

        logger.info(
            f"Finished executing tools with {len(tool_results_for_llm)} results."
        )
        yield {"type": "final_tool_results", "results": tool_results_for_llm}

    async def run_single_tool(
        self, tool_name: str, tool_id: str, tool_input: Any
    ) -> tuple[bool, str, Dict[str, Any], List[Dict[str, Any]]]:
        """Run a single tool using MCPClient.

        Returns:
            tuple: (is_error, text_content, metadata, content_items)
        """
        logger.info(f"Executing tool: {tool_name} (ID: {tool_id})")
        tool_info = self._tool_manager.get_tool(tool_name)

        is_error = False
        text_content = ""
        metadata = {}
        content_items = []

        if tool_input is None:
            tool_input = {}

        if not tool_info:
            logger.error(f"Tool '{tool_name}' not found in ToolManager.")
            text_content = f"Error: Tool '{tool_name}' is not available."
            content_items = [{"type": "error", "text": text_content}]
            is_error = True
        elif not tool_info.related_server:
            logger.error(f"Tool '{tool_name}' does not have a related server defined.")
            text_content = f"Error: Configuration error for tool '{tool_name}'. No server specified."
            content_items = [{"type": "error", "text": text_content}]
            is_error = True
        else:
            try:
                result_dict = await self._mcp_client.call_tool(
                    server_name=tool_info.related_server,
                    tool_name=tool_name,
                    tool_args=tool_input,
                )

                metadata = result_dict.get("metadata", {})
                content_items = result_dict.get("content_items", [])

                # Check if the first content item is an error reported by MCPClient
                if content_items and content_items[0].get("type") == "error":
                    is_error = True
                    text_content = content_items[0].get(
                        "text", "Unknown error from tool execution."
                    )
                elif content_items and content_items[0].get("type") == "text":
                    text_content = content_items[0].get("text", "")
                # If no text item is first, text_content remains ""

                if not is_error:
                    logger.info(f"Tool '{tool_name}' executed successfully.")
                    if content_items:
                        logger.info(f"Content items from tool '{tool_name}':")
                        for item in content_items:
                            item_type = item.get("type", "unknown")
                            logger.info(f"  Type: {item_type}")
                            for key, value in item.items():
                                if (
                                    key != "type" and key != "data"
                                ):  # Avoid logging large data
                                    log_value = (
                                        f"(length: {len(value)})"
                                        if isinstance(value, str) and len(value) > 100
                                        else value
                                    )
                                    logger.info(f"    {key}: {log_value}")

            except (ValueError, RuntimeError, ConnectionError) as e:
                logger.exception(f"Error executing tool '{tool_name}': {e}")
                text_content = f"Error executing tool '{tool_name}': {e}"
                content_items = [{"type": "error", "text": text_content}]
                is_error = True
            except Exception as e:
                logger.exception(f"Unexpected error executing tool '{tool_name}': {e}")
                text_content = f"Unexpected error executing tool '{tool_name}': {e}"
                content_items = [{"type": "error", "text": text_content}]
                is_error = True

        return is_error, text_content, metadata, content_items
