"""arXiv tool using the arXiv API (no API key required)."""
from __future__ import annotations

import httpx
import xml.etree.ElementTree as ET
from .base import BaseTool, ToolResult

_BASE = "https://export.arxiv.org/api/query"
_TIMEOUT = 15
_NS = "http://www.w3.org/2005/Atom"


class ArxivTool(BaseTool):
    name = "arxiv"
    description = (
        "Search arXiv for academic papers. Best for recent research, machine learning "
        "applications in finance, quantitative methods, and emerging academic topics. "
        "Input: a search query string (e.g. 'machine learning credit risk 2023')."
    )

    def run(self, query: str, max_results: int = 5) -> ToolResult:
        try:
            params = {
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": max_results,
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
            resp = httpx.get(_BASE, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()

            papers = self._parse(resp.text)
            if not papers:
                return ToolResult(
                    tool_name=self.name, query=query,
                    results=[], summary="No arXiv papers found.",
                    source_urls=[],
                )

            source_urls = [p["url"] for p in papers]
            lines = []
            for p in papers:
                authors = ", ".join(p["authors"][:3])
                if len(p["authors"]) > 3:
                    authors += " et al."
                lines.append(
                    f"**{p['title']}** ({p['published'][:4]})\n"
                    f"Authors: {authors}\n"
                    f"arXiv ID: {p['id']}\n"
                    f"Abstract: {p['abstract'][:400]}...\n"
                    f"URL: {p['url']}"
                )

            summary = "\n\n---\n\n".join(lines)
            return ToolResult(
                tool_name=self.name,
                query=query,
                results=papers,
                summary=summary,
                source_urls=source_urls,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name, query=query,
                results=[], summary="", source_urls=[],
                error=str(exc),
            )

    def _parse(self, xml_text: str) -> list[dict]:
        root = ET.fromstring(xml_text)
        papers = []
        for entry in root.findall(f"{{{_NS}}}entry"):
            raw_id = entry.findtext(f"{{{_NS}}}id", "")
            arxiv_id = raw_id.split("/abs/")[-1].strip()
            title = entry.findtext(f"{{{_NS}}}title", "").replace("\n", " ").strip()
            abstract = entry.findtext(f"{{{_NS}}}summary", "").replace("\n", " ").strip()
            published = entry.findtext(f"{{{_NS}}}published", "")
            authors = [
                a.findtext(f"{{{_NS}}}name", "")
                for a in entry.findall(f"{{{_NS}}}author")
            ]
            papers.append({
                "id": arxiv_id,
                "title": title,
                "abstract": abstract,
                "published": published,
                "authors": authors,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
            })
        return papers
