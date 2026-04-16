"""Tool registry — single place to register and look up tools."""
from __future__ import annotations

from tools.base import BaseTool


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def all(self) -> list[BaseTool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def descriptions_for_prompt(self) -> str:
        """Format tool descriptions for injection into the system prompt."""
        lines = []
        for tool in self._tools.values():
            lines.append(f"- **{tool.name}**: {tool.description}")
        return "\n".join(lines)


def build_default_registry() -> ToolRegistry:
    """Instantiate and register all available tools."""
    from tools.wikipedia import WikipediaTool
    from tools.arxiv import ArxivTool
    from tools.fred import FredTool

    registry = ToolRegistry()
    registry.register(WikipediaTool())
    registry.register(ArxivTool())

    fred = FredTool()
    registry.register(fred)
    if not fred.available:
        print("  [registry] FRED tool registered but disabled (no FRED_API_KEY).")

    return registry
