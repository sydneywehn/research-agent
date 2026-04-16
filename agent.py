#!/usr/bin/env python3
"""
Research Agent CLI
Usage: python agent.py "your question here"
"""

import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env from repo root
load_dotenv(Path(__file__).parent / ".env")

from core.llm import LLMClient
from core.tool_registry import build_default_registry
from core.tracer import Tracer
from core.agent import ResearchAgent


def main():
    if len(sys.argv) < 2:
        print("Usage: python agent.py \"your research question\"")
        sys.exit(1)

    question = " ".join(sys.argv[1:])

    print(f"\nQuestion: {question}")
    print("=" * 60)

    llm = LLMClient()
    registry = build_default_registry()
    tracer = Tracer()
    agent = ResearchAgent(llm, registry, tracer)

    answer, trace = agent.run(question)

    print(f"\n{answer}")

    if trace.citations:
        print("\nSources:")
        for url in trace.citations:
            if url:
                print(f"  - {url}")

    print(f"\n[Trace saved: traces/{trace.run_id}.json | steps: {trace.total_steps} | {trace.total_duration_seconds:.1f}s]")


if __name__ == "__main__":
    main()
