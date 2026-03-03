from __future__ import annotations

import dataclasses
import time
from typing import Any, AsyncIterator, Dict, List

from loguru import logger

from .stateless_llm_interface import StatelessLLMInterface


class LangfuseWrapperLLM(StatelessLLMInterface):
    """Optional Langfuse tracing wrapper for any stateless LLM."""

    def __init__(
        self,
        wrapped_llm: StatelessLLMInterface,
        public_key: str,
        secret_key: str,
        host: str | None = None,
    ):
        self.wrapped_llm = wrapped_llm
        self.model = getattr(wrapped_llm, "model", type(wrapped_llm).__name__)
        self.provider = type(wrapped_llm).__name__

        self._langfuse = None
        self._enabled = False

        try:
            from langfuse import Langfuse
        except ImportError:
            logger.warning(
                "Langfuse is not installed. Install with: uv sync --extra observability"
            )
            return

        try:
            init_kwargs = {
                "public_key": public_key,
                "secret_key": secret_key,
            }
            if host:
                init_kwargs["host"] = host
            self._langfuse = Langfuse(**init_kwargs)
            self._enabled = True
            logger.info(
                f"Langfuse tracing enabled for provider={self.provider}, model={self.model}"
            )
        except Exception as exc:
            logger.warning(f"Failed to initialize Langfuse client: {exc}")

    def __getattr__(self, name: str) -> Any:
        return getattr(self.wrapped_llm, name)

    def _serialize(self, obj: Any) -> Any:
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if dataclasses.is_dataclass(obj):
            return self._serialize(dataclasses.asdict(obj))
        if isinstance(obj, dict):
            return {str(k): self._serialize(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [self._serialize(item) for item in obj]
        if hasattr(obj, "model_dump") and callable(obj.model_dump):
            try:
                return self._serialize(obj.model_dump(exclude_none=True))
            except Exception:
                return str(obj)
        if hasattr(obj, "dict") and callable(obj.dict):
            try:
                return self._serialize(obj.dict())
            except Exception:
                return str(obj)
        if hasattr(obj, "__dict__"):
            try:
                return self._serialize(vars(obj))
            except Exception:
                return str(obj)
        return str(obj)

    def _safe_end_generation(self, generation: Any, output: Dict[str, Any]) -> None:
        if not generation:
            return

        try:
            generation.end(output=output)
            if self._langfuse:
                self._langfuse.flush()
        except Exception as exc:
            logger.warning(f"Failed to finalize Langfuse generation: {exc}")

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        system: str = None,
        tools: List[Dict[str, Any]] = None,
        **kwargs,
    ) -> AsyncIterator[Any]:
        input_payload = {
            "messages": self._serialize(messages),
            "system": system,
            "tools": self._serialize(tools),
            "kwargs": self._serialize(kwargs),
        }
        metadata = {
            "provider": self.provider,
            "model": self.model,
        }

        trace = None
        generation = None
        t0 = time.perf_counter()

        if self._enabled and self._langfuse:
            try:
                trace = self._langfuse.trace(
                    name="open-llm-vtuber.chat_completion",
                    input=input_payload,
                    metadata=metadata,
                )
                generation = trace.generation(
                    name="chat.completion",
                    model=str(self.model),
                    input=input_payload,
                    metadata=metadata,
                )
            except Exception as exc:
                logger.warning(f"Failed to start Langfuse trace/generation: {exc}")

        output_text = ""
        tool_events: List[Any] = []

        try:
            stream = self.wrapped_llm.chat_completion(
                messages,
                system,
                tools=tools,
                **kwargs,
            )
            async for event in stream:
                if isinstance(event, str):
                    output_text += event
                elif isinstance(event, dict):
                    if event.get("type") == "text_delta":
                        output_text += event.get("text", "")
                    elif "tool" in str(event.get("type", "")):
                        tool_events.append(self._serialize(event))
                elif isinstance(event, list):
                    tool_events.append(self._serialize(event))

                yield event

            if generation:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                output_payload = {
                    "text": output_text,
                    "tool_events": tool_events,
                    "status": "success",
                    "duration_ms": elapsed_ms,
                }
                self._safe_end_generation(generation, output_payload)

        except Exception as exc:
            if generation:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                self._safe_end_generation(
                    generation,
                    {
                        "text": output_text,
                        "tool_events": tool_events,
                        "status": "error",
                        "duration_ms": elapsed_ms,
                        "error": str(exc),
                    },
                )
            raise
