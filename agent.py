#!/usr/bin/env python3
"""
Research Agent CLI
Usage: python agent.py "your question here"
       python agent.py --single-pass "your question here"
"""

import argparse
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
    parser = argparse.ArgumentParser(description="Banking research agent")
    parser.add_argument("--single-pass", action="store_true",
                        help="Limit reasoning to 1 step (no multi-step tool chaining)")
    parser.add_argument("question", nargs="+", help="Research question")
    args = parser.parse_args()

    question = " ".join(args.question)
    max_steps = 1 if args.single_pass else None

    print(f"\nQuestion: {question}")
    if args.single_pass:
        print("[single-pass mode]")
    print("=" * 60)

    llm = LLMClient()
    registry = build_default_registry()
    tracer = Tracer()
    agent = ResearchAgent(llm, registry, tracer, max_steps=max_steps)

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
