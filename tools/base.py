from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolResult:
    tool_name: str
    query: str
    results: list[dict]
    summary: str          # compact text injected into LLM context
    source_urls: list[str]
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None

    def to_context_str(self) -> str:
        """Format for injection into the ReAct loop context."""
        if not self.success:
            return f"[{self.tool_name}] ERROR: {self.error}"
        return f"[{self.tool_name} results for '{self.query}']\n{self.summary}"


class BaseTool(ABC):
    name: str
    description: str

    @abstractmethod
    def run(self, query: str) -> ToolResult:
        """Execute the tool and return a structured result."""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
