"""Wikipedia tool using the MediaWiki REST API (no API key required)."""
from __future__ import annotations

import httpx
from urllib.parse import quote
from .base import BaseTool, ToolResult

_BASE = "https://en.wikipedia.org/api/rest_v1"
_SEARCH = "https://en.wikipedia.org/w/api.php"
_TIMEOUT = 10
_HEADERS = {"User-Agent": "BankingResearchAgent/1.0 (educational project; contact: research-agent)"}


class WikipediaTool(BaseTool):
    name = "wikipedia"
    description = (
        "Search Wikipedia for encyclopedia articles. Best for factual background, "
        "definitions, regulatory history, and general finance/economics concepts. "
        "Input: a search query string."
    )

    def run(self, query: str) -> ToolResult:
        try:
            titles = self._search(query)
            if not titles:
                return ToolResult(
                    tool_name=self.name, query=query,
                    results=[], summary="No Wikipedia articles found.",
                    source_urls=[], error=None,
                )

            articles = []
            source_urls = []
            summaries = []

            for title in titles[:3]:
                article = self._fetch_summary(title)
                if article:
                    articles.append(article)
                    source_urls.append(article["url"])
                    summaries.append(
                        f"**{article['title']}**\n{article['extract']}"
                    )

            combined_summary = "\n\n---\n\n".join(summaries)
            return ToolResult(
                tool_name=self.name,
                query=query,
                results=articles,
                summary=combined_summary,
                source_urls=source_urls,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name, query=query,
                results=[], summary="", source_urls=[],
                error=str(exc),
            )

    def _search(self, query: str) -> list[str]:
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 3,
            "format": "json",
        }
        resp = httpx.get(_SEARCH, params=params, timeout=_TIMEOUT, headers=_HEADERS)
        resp.raise_for_status()
        results = resp.json().get("query", {}).get("search", [])
        return [r["title"] for r in results]

    def _fetch_summary(self, title: str) -> dict | None:
        encoded = quote(title.replace(" ", "_"), safe="")
        url = f"{_BASE}/page/summary/{encoded}"
        try:
            resp = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
            return {
                "title": data.get("title", title),
                "extract": data.get("extract", ""),
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            }
        except Exception:
            return None
