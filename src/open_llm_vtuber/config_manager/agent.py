"""Agent configuration for Pi and Hermes runtimes."""

from pydantic import BaseModel, Field
from typing import Dict, ClassVar, Optional, Literal
from .i18n import I18nMixin, Description
from .stateless_llm import StatelessLLMConfigs


class PiAgentConfig(I18nMixin, BaseModel):
    """Configuration for the pi agent (wraps pi-python-client)."""

    faster_first_response: Optional[bool] = Field(True, alias="faster_first_response")
    segment_method: Literal["regex", "pysbd", "none"] = Field(
        "pysbd", alias="segment_method"
    )
    interrupt_method: Literal["system", "user"] = Field("user", alias="interrupt_method")
    pi_session_dir: Optional[str] = Field(None, alias="pi_session_dir")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "faster_first_response": Description(
            en="Whether to respond as soon as encountering a comma in the first sentence to reduce latency (default: True)",
            zh="是否在第一句回应时遇上逗号就直接生成音频以减少首句延迟（默认：True）",
        ),
        "segment_method": Description(
            en="Method for segmenting sentences: 'regex', 'pysbd', or 'none' (default: 'pysbd')",
            zh="分割句子的方法：'regex'、'pysbd' 或 'none'（默认：'pysbd'）",
        ),
        "interrupt_method": Description(
            en="How to signal interrupts to the LLM: 'system' or 'user' (default: 'user')",
            zh="向 LLM 发送中断信号的方式：'system' 或 'user'（默认：'user'）",
        ),
        "pi_session_dir": Description(
            en="Directory for pi session files (default: ~/.pi/vtuber_sessions)",
            zh="pi 会话文件目录（默认：~/.pi/vtuber_sessions）",
        ),
    }


class HermesAgentConfig(I18nMixin, BaseModel):
    """Configuration for the Hermes ACP runtime adapter."""

    hermes_bin: Optional[str] = Field(None, alias="hermes_bin")
    hermes_cwd: Optional[str] = Field(None, alias="hermes_cwd")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "hermes_bin": Description(
            en="Path or command name for hermes executable (default: hermes)",
            zh="hermes 可执行文件路径或命令名（默认：hermes）",
        ),
        "hermes_cwd": Description(
            en="Working directory for hermes acp subprocess (default: current directory)",
            zh="hermes acp 子进程工作目录（默认：当前目录）",
        ),
    }


class AgentSettings(I18nMixin, BaseModel):
    """Settings for conversation agents."""

    pi_agent: Optional[PiAgentConfig] = Field(None, alias="pi_agent")
    hermes_agent: Optional[HermesAgentConfig] = Field(None, alias="hermes_agent")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "pi_agent": Description(
            en="Configuration for pi agent (pi-python-client wrapper)",
            zh="pi 代理配置（pi-python-client 封装）",
        ),
        "hermes_agent": Description(
            en="Configuration for hermes agent (RPC runtime adapter)",
            zh="hermes 代理配置（RPC 运行时适配器）",
        ),
    }


class AgentConfig(I18nMixin, BaseModel):
    """Agent configuration."""

    conversation_agent_choice: Literal["pi_agent", "hermes_agent"] = Field(
        "pi_agent", alias="conversation_agent_choice"
    )
    agent_settings: AgentSettings = Field(
        default_factory=lambda: AgentSettings(), alias="agent_settings"
    )
    # llm_configs kept so existing conf.yaml files that still have the block don't fail validation
    llm_configs: Optional[StatelessLLMConfigs] = Field(None, alias="llm_configs")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "conversation_agent_choice": Description(
            en="Type of conversation agent to use", zh="要使用的对话代理类型"
        ),
        "agent_settings": Description(
            en="Settings for available conversation agents", zh="可用对话代理设置"
        ),
        "llm_configs": Description(
            en="Unused when using pi/hermes runtime agent — kept for conf.yaml compatibility",
            zh="使用 pi/hermes 运行时代理时不需要，保留用于兼容 conf.yaml",
        ),
    }
