from typing import Any, AsyncIterator, Dict, List
import asyncio

import httpx
from loguru import logger

from .stateless_llm_interface import StatelessLLMInterface


class NullclawGatewayLLM(StatelessLLMInterface):
    """Stateless adapter that forwards prompts to a nullclaw gateway webhook."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:5001",
        webhook_path: str = "/webhook",
        bearer_token: str | None = None,
        request_timeout_sec: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.webhook_path = (
            webhook_path if webhook_path.startswith("/") else f"/{webhook_path}"
        )
        self.url = f"{self.base_url}{self.webhook_path}"
        self.bearer_token = bearer_token
        self.request_timeout_sec = request_timeout_sec

        logger.info(
            f"Initialized NullclawGatewayLLM: base_url={self.base_url}, webhook_path={self.webhook_path}"
        )

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            parts.append(text.strip())
                    elif item.get("type") == "image_url":
                        parts.append("[User provided image]")
            return "\n".join(parts).strip()
        return ""

    def _build_prompt(self, messages: List[Dict[str, Any]], system: str | None) -> str:
        user_text = ""
        for msg in reversed(messages):
            if msg.get("role") != "user":
                continue
            candidate = self._extract_text_content(msg.get("content"))
            if candidate:
                user_text = candidate
                break

        if not user_text:
            for msg in reversed(messages):
                candidate = self._extract_text_content(msg.get("content"))
                if candidate:
                    user_text = candidate
                    break

        if not user_text:
            user_text = "..."

        if system and system.strip():
            return f"{system.strip()}\n\n{user_text}"
        return user_text

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        system: str = None,
        tools: List[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        del (
            tools
        )  # nullclaw handles tools on its side; webhook API is text-in/text-out.

        prompt = self._build_prompt(messages, system)
        headers = {"Content-Type": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"

        try:
            async with httpx.AsyncClient(
                timeout=self.request_timeout_sec,
                trust_env=False,
            ) as client:
                response = await client.post(
                    self.url,
                    json={"message": prompt},
                    headers=headers,
                )
                response.raise_for_status()

                payload = response.json()
                if payload.get("status") == "received":
                    await asyncio.sleep(0.35)
                    response = await client.post(
                        self.url,
                        json={"message": prompt},
                        headers=headers,
                    )
                    response.raise_for_status()
                    payload = response.json()

            reply = payload.get("response") or payload.get("reply")
            if not isinstance(reply, str) or not reply:
                status = payload.get("status")
                if status == "received":
                    raise ValueError(
                        "Nullclaw webhook returned async ack only ('status=received'). "
                        "Restart nullclaw using the latest binary so /webhook returns synchronous text responses."
                    )
                raise ValueError(
                    f"Nullclaw webhook response missing text field 'response': {payload}"
                )

            yield reply

        except httpx.HTTPStatusError as exc:
            logger.error(
                f"Nullclaw webhook HTTP error {exc.response.status_code}: {exc.response.text}"
            )
            yield "Error calling nullclaw gateway webhook: HTTP error. See logs for details."
        except Exception as exc:
            logger.error(f"Nullclaw gateway error: {exc}")
            yield "Error calling nullclaw gateway webhook. See logs for details."
