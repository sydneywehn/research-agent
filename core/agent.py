"""ReAct research agent with upfront classifier."""
from __future__ import annotations

import json
import time
from dataclasses import asdict

from core.llm import LLMClient
from core.tool_registry import ToolRegistry
from core.tracer import RunTrace, StepTrace, Tracer
from tools.base import ToolResult

MAX_STEPS = 8

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

CLASSIFIER_PROMPT = """\
You are a classifier for a banking and finance research assistant.
Determine whether the following question is in-scope for financial/economic research.

In-scope: banking regulations, monetary policy, macroeconomics, financial instruments,
academic finance research, economic data, central banks, credit, investment theory.

Out-of-scope: restaurants, sports, entertainment, personal advice, non-financial topics.
Speculative/emerging tech questions (e.g. quantum computing + banking) are IN-SCOPE — caveat appropriately.

Respond with JSON matching this schema exactly:
{{
  "scope": "in_scope" | "out_of_scope",
  "reason": "<one sentence explanation>",
  "domain": "factual" | "academic" | "data" | "multi_source" | "speculative"
}}

Question: {question}
"""

SYSTEM_PROMPT = """\
You are a rigorous financial research assistant. You answer questions by calling tools \
and synthesizing the results into a cited, accurate response.

Available tools:
{tool_descriptions}

You operate in a ReAct loop. At each step output a JSON object with one of two shapes:

1. To call a tool:
{{
  "thought": "<your reasoning about what to search next>",
  "action": {{"tool": "<tool_name>", "query": "<search query>"}}
}}

2. To deliver your final answer (when you have enough information):
{{
  "thought": "<brief summary of what you found>",
  "final_answer": "<your complete synthesized answer with inline citations>",
  "citations": ["<url1>", "<url2>", ...]
}}

Rules:
- Always cite sources. Use the URLs returned by tools.
- Distinguish between retrieved facts and your own reasoning/inference.
- If a tool returns an error, try a different query or tool before giving up.
- For multi-part questions, gather information on each part before synthesizing.
- Do not repeat a tool call with the identical query. Rephrase if needed.
- Domain hint for this question: {domain}
"""

STEP_PROMPT = """\
{system}

Question: {question}

{history}

Step {step} — respond with JSON only:"""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ResearchAgent:
    def __init__(self, llm: LLMClient, registry: ToolRegistry, tracer: Tracer, max_steps: int | None = None):
        self._llm = llm
        self._registry = registry
        self._tracer = tracer
        self._max_steps = max_steps if max_steps is not None else MAX_STEPS

    def run(self, question: str) -> tuple[str, RunTrace]:
        trace = self._tracer.new_run(question)
        start = time.time()

        # 1. Classify
        classifier_result = self._classify(question)
        trace.classifier = classifier_result

        if classifier_result["scope"] == "out_of_scope":
            answer = (
                f"This question is outside the scope of this financial research assistant.\n\n"
                f"Reason: {classifier_result['reason']}\n\n"
                f"I can help with banking regulations, monetary policy, economic data, "
                f"academic finance research, and related topics."
            )
            trace.finish(answer, [], time.time() - start)
            self._tracer.save(trace)
            return answer, trace

        # 2. ReAct loop
        domain = classifier_result.get("domain", "factual")
        system = SYSTEM_PROMPT.format(
            tool_descriptions=self._registry.descriptions_for_prompt(),
            domain=domain,
        )

        history_parts: list[str] = []
        all_citations: list[str] = []
        used_queries: set[str] = set()

        for step_num in range(1, self._max_steps + 1):
            history = "\n\n".join(history_parts) if history_parts else "(no steps yet)"
            prompt = STEP_PROMPT.format(
                system=system,
                question=question,
                history=history,
                step=step_num,
            )

            step_start = time.time()
            raw = self._llm.generate_json(prompt)
            step_duration = time.time() - step_start

            thought = raw.get("thought", "")

            if "final_answer" in raw:
                answer = raw["final_answer"]
                citations = raw.get("citations", [])
                all_citations.extend(citations)
                # Add any URLs collected from tool results not already cited
                for url in all_citations:
                    if url not in citations:
                        citations.append(url)

                step_trace = StepTrace(
                    step=step_num, thought=thought,
                    action=None, observation=None,
                    duration_seconds=step_duration,
                )
                trace.add_step(step_trace)
                trace.finish(answer, list(dict.fromkeys(citations)), time.time() - start)
                self._tracer.save(trace)
                return answer, trace

            action = raw.get("action", {})
            tool_name = action.get("tool", "")
            query = action.get("query", "")

            # Dedup: don't repeat the same query on the same tool
            dedup_key = f"{tool_name}::{query}"
            if dedup_key in used_queries:
                history_parts.append(
                    f"[Step {step_num}] Thought: {thought}\n"
                    f"Skipped duplicate tool call ({tool_name}: '{query}')."
                )
                continue
            used_queries.add(dedup_key)

            tool = self._registry.get(tool_name)
            if not tool:
                obs_str = f"[ERROR] Unknown tool '{tool_name}'. Available: {self._registry.names()}"
                obs_dict = {"error": obs_str}
            else:
                result: ToolResult = tool.run(query)
                obs_str = result.to_context_str()
                obs_dict = asdict(result)
                all_citations.extend(result.source_urls)

            step_trace = StepTrace(
                step=step_num,
                thought=thought,
                action={"tool": tool_name, "query": query},
                observation=obs_dict,
                duration_seconds=step_duration,
            )
            trace.add_step(step_trace)

            history_parts.append(
                f"[Step {step_num}] Thought: {thought}\n"
                f"Action: {tool_name}('{query}')\n"
                f"Observation:\n{obs_str}"
            )

        # Hit step limit — ask LLM to synthesize what it has
        history = "\n\n".join(history_parts)
        final_prompt = (
            f"{system}\n\nQuestion: {question}\n\n{history}\n\n"
            f"You have reached the step limit. Synthesize the best answer you can "
            f"from the information gathered above. Respond with JSON: "
            f'{{ "thought": "...", "final_answer": "...", "citations": [...] }}'
        )
        raw = self._llm.generate_json(final_prompt)
        answer = raw.get("final_answer", "Unable to synthesize a complete answer.")
        citations = list(dict.fromkeys(all_citations))

        trace.finish(answer, citations, time.time() - start)
        self._tracer.save(trace)
        return answer, trace

    def _classify(self, question: str) -> dict:
        prompt = CLASSIFIER_PROMPT.format(question=question)
        try:
            return self._llm.generate_json(prompt)
        except Exception:
            # Default to in-scope on classifier failure
            return {"scope": "in_scope", "reason": "classifier failed", "domain": "factual"}
