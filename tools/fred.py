"""FRED (Federal Reserve Economic Data) tool. Requires FRED_API_KEY env var.
If the key is absent, the tool is disabled and returns a graceful error."""
from __future__ import annotations

import os
import httpx
from .base import BaseTool, ToolResult

_BASE = "https://api.stlouisfed.org/fred"
_TIMEOUT = 10


class FredTool(BaseTool):
    name = "fred"
    description = (
        "Retrieve US economic data from the Federal Reserve (FRED). Best for current "
        "and historical statistics: unemployment rate, GDP, federal funds rate, "
        "inflation, interest rates. Input: a description of the economic indicator "
        "you want (e.g. 'unemployment rate', 'federal funds rate', 'US GDP growth')."
    )

    def __init__(self):
        self._api_key = os.environ.get("FRED_API_KEY")

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def run(self, query: str) -> ToolResult:
        if not self.available:
            return ToolResult(
                tool_name=self.name, query=query,
                results=[], summary="FRED tool unavailable (no FRED_API_KEY set).",
                source_urls=[],
                error="FRED_API_KEY not configured",
            )
        try:
            series_id = self._find_series(query)
            if not series_id:
                return ToolResult(
                    tool_name=self.name, query=query,
                    results=[], summary=f"No FRED series found for: {query}",
                    source_urls=[],
                )
            return self._fetch_series(series_id, query)
        except Exception as exc:
            return ToolResult(
                tool_name=self.name, query=query,
                results=[], summary="", source_urls=[],
                error=str(exc),
            )

    def _find_series(self, query: str) -> str | None:
        """Search FRED for the most relevant series ID."""
        params = {
            "search_text": query,
            "api_key": self._api_key,
            "file_type": "json",
            "limit": 5,
            "order_by": "popularity",
            "sort_order": "desc",
        }
        resp = httpx.get(f"{_BASE}/series/search", params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        seriess = resp.json().get("seriess", [])
        if not seriess:
            return None
        # Prefer monthly or quarterly series over daily
        for s in seriess:
            if s.get("frequency_short") in ("M", "Q", "A"):
                return s["id"]
        return seriess[0]["id"]

    def _fetch_series(self, series_id: str, original_query: str) -> ToolResult:
        """Fetch series metadata and last 13 observations (~1 year for monthly)."""
        # Metadata
        meta_params = {"series_id": series_id, "api_key": self._api_key, "file_type": "json"}
        meta_resp = httpx.get(f"{_BASE}/series", params=meta_params, timeout=_TIMEOUT)
        meta_resp.raise_for_status()
        series_info = meta_resp.json().get("seriess", [{}])[0]

        # Observations
        obs_params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 13,
        }
        obs_resp = httpx.get(f"{_BASE}/series/observations", params=obs_params, timeout=_TIMEOUT)
        obs_resp.raise_for_status()
        observations = obs_resp.json().get("observations", [])
        observations = list(reversed(observations))  # chronological order

        name = series_info.get("title", series_id)
        units = series_info.get("units_short", "")
        freq = series_info.get("frequency_short", "")
        source_url = f"https://fred.stlouisfed.org/series/{series_id}"

        if not observations:
            return ToolResult(
                tool_name=self.name, query=original_query,
                results=[], summary=f"No observations found for {name}.",
                source_urls=[source_url],
            )

        latest = observations[-1]
        latest_val = latest.get("value", "N/A")
        latest_date = latest.get("date", "")

        # Build summary
        obs_lines = [
            f"  {o['date']}: {o['value']} {units}"
            for o in observations
            if o.get("value") not in (".", None)
        ]
        summary = (
            f"**{name}** (Series: {series_id}, Frequency: {freq})\n"
            f"Latest value: {latest_val} {units} as of {latest_date}\n\n"
            f"Recent observations:\n" + "\n".join(obs_lines)
        )

        results = [{
            "series_id": series_id,
            "name": name,
            "units": units,
            "frequency": freq,
            "latest_value": latest_val,
            "latest_date": latest_date,
            "observations": observations,
        }]

        return ToolResult(
            tool_name=self.name,
            query=original_query,
            results=results,
            summary=summary,
            source_urls=[source_url],
        )
