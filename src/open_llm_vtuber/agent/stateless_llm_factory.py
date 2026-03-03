from typing import Type

from loguru import logger

from .stateless_llm.stateless_llm_interface import StatelessLLMInterface
from .stateless_llm.stateless_llm_with_template import (
    AsyncLLMWithTemplate as StatelessLLMWithTemplate,
)
from .stateless_llm.openai_compatible_llm import AsyncLLM as OpenAICompatibleLLM
from .stateless_llm.ollama_llm import OllamaLLM
from .stateless_llm.claude_llm import AsyncLLM as ClaudeLLM
from .stateless_llm.langfuse_wrapper_llm import LangfuseWrapperLLM
from .stateless_llm.nullclaw_gateway_llm import NullclawGatewayLLM


class LLMFactory:
    @staticmethod
    def _maybe_wrap_with_langfuse(
        llm: Type[StatelessLLMInterface], llm_provider: str, kwargs: dict
    ) -> Type[StatelessLLMInterface]:
        if not kwargs.get("langfuse_enabled", False):
            return llm

        public_key = kwargs.get("langfuse_public_key")
        secret_key = kwargs.get("langfuse_secret_key")
        host = kwargs.get("langfuse_host")

        if not public_key or not secret_key:
            logger.warning(
                f"Langfuse is enabled for '{llm_provider}' but keys are missing. "
                "Proceeding without Langfuse tracing."
            )
            return llm

        try:
            return LangfuseWrapperLLM(
                wrapped_llm=llm,
                public_key=public_key,
                secret_key=secret_key,
                host=host,
            )
        except Exception as exc:
            logger.warning(
                f"Unable to enable Langfuse tracing for '{llm_provider}': {exc}"
            )
            return llm

    @staticmethod
    def create_llm(llm_provider, **kwargs) -> Type[StatelessLLMInterface]:
        """Create an LLM based on the configuration.

        Args:
            llm_provider: The type of LLM to create
            **kwargs: Additional arguments
        """
        logger.info(f"Initializing LLM: {llm_provider}")

        if (
            llm_provider == "openai_compatible_llm"
            or llm_provider == "openai_llm"
            or llm_provider == "gemini_llm"
            or llm_provider == "zhipu_llm"
            or llm_provider == "deepseek_llm"
            or llm_provider == "groq_llm"
            or llm_provider == "mistral_llm"
            or llm_provider == "lmstudio_llm"
        ):
            llm = OpenAICompatibleLLM(
                model=kwargs.get("model"),
                base_url=kwargs.get("base_url"),
                llm_api_key=kwargs.get("llm_api_key"),
                organization_id=kwargs.get("organization_id"),
                project_id=kwargs.get("project_id"),
                temperature=kwargs.get("temperature"),
            )
            return LLMFactory._maybe_wrap_with_langfuse(llm, llm_provider, kwargs)
        if llm_provider == "stateless_llm_with_template":
            llm = StatelessLLMWithTemplate(
                model=kwargs.get("model"),
                base_url=kwargs.get("base_url"),
                llm_api_key=kwargs.get("llm_api_key"),
                organization_id=kwargs.get("organization_id"),
                template=kwargs.get("template"),
                project_id=kwargs.get("project_id"),
            )
            return LLMFactory._maybe_wrap_with_langfuse(llm, llm_provider, kwargs)
        if llm_provider == "ollama_llm":
            llm = OllamaLLM(
                model=kwargs.get("model"),
                base_url=kwargs.get("base_url"),
                llm_api_key=kwargs.get("llm_api_key"),
                organization_id=kwargs.get("organization_id"),
                project_id=kwargs.get("project_id"),
                temperature=kwargs.get("temperature"),
                keep_alive=kwargs.get("keep_alive"),
                unload_at_exit=kwargs.get("unload_at_exit"),
            )
            return LLMFactory._maybe_wrap_with_langfuse(llm, llm_provider, kwargs)

        elif llm_provider == "llama_cpp_llm":
            from .stateless_llm.llama_cpp_llm import LLM as LlamaLLM

            llm = LlamaLLM(
                model_path=kwargs.get("model_path"),
            )
            return LLMFactory._maybe_wrap_with_langfuse(llm, llm_provider, kwargs)
        elif llm_provider == "claude_llm":
            llm = ClaudeLLM(
                system=kwargs.get("system_prompt"),
                base_url=kwargs.get("base_url"),
                model=kwargs.get("model"),
                llm_api_key=kwargs.get("llm_api_key"),
            )
            return LLMFactory._maybe_wrap_with_langfuse(llm, llm_provider, kwargs)
        elif llm_provider == "nullclaw_gateway_llm":
            llm = NullclawGatewayLLM(
                base_url=kwargs.get("base_url"),
                webhook_path=kwargs.get("webhook_path"),
                bearer_token=kwargs.get("bearer_token"),
                request_timeout_sec=kwargs.get("request_timeout_sec"),
            )
            return LLMFactory._maybe_wrap_with_langfuse(llm, llm_provider, kwargs)
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_provider}")


# Creating an LLM instance using a factory
# llm_instance = LLMFactory.create_llm("ollama", **config_dict)
