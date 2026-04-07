"""crew_chief — local Ollama LLM client and agentic workflow engine."""

from crew_chief.agent import Agent
from crew_chief.client import CrewChiefClient
from crew_chief.providers import (
    AnthropicProvider,
    ClaudeCliProvider,
    CodexCliProvider,
    FallbackProvider,
    OllamaProvider,
    OpenAIProvider,
    ProviderUnavailableError,
    get_provider,
)
from crew_chief.tools import ReadFileTool, ShellTool, Tool, WriteFileTool, build_tools

__all__ = [
    "Agent",
    "AnthropicProvider",
    "ClaudeCliProvider",
    "CodexCliProvider",
    "CrewChiefClient",
    "FallbackProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "ProviderUnavailableError",
    "ReadFileTool",
    "ShellTool",
    "Tool",
    "WriteFileTool",
    "build_tools",
    "get_provider",
]
__version__ = "0.2.0"
