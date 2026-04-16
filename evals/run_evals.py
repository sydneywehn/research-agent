#!/usr/bin/env python3
"""
Evaluation harness for the research agent.
Usage:
  python evals/run_evals.py                  # run all questions
  python evals/run_evals.py --ids q01 q07   # run specific questions
  python evals/run_evals.py --category academic
"""

import argparse
import json
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.llm import LLMClient
from core.tool_registry import build_default_registry
from core.tracer import Tracer
from core.agent import ResearchAgent

BENCHMARK = Path(__file__).parent / "benchmark.json"
RESULTS_DIR = Path(__file__).parent / "results"


def score_answer(answer: str, trace, spec: dict) -> dict:
    """Score a single answer against its benchmark spec."""
    answer_lower = answer.lower()

    # Required facts present
    required = spec.get("required_facts", [])
    found = [f for f in required if f.lower() in answer_lower]
    required_score = len(found) / len(required) if required else 1.0

    # Forbidden facts absent
    forbidden = spec.get("forbidden_facts", [])
    violations = [f for f in forbidden if f.lower() in answer_lower]
    forbidden_ok = len(violations) == 0

    # Behavior correct (answer vs refuse)
    expected_behavior = spec.get("expected_behavior", "answer")
    if expected_behavior == "refuse":
        # A refusal should NOT contain the forbidden facts and should be short / not cite sources
        behavior_correct = len(trace.citations) == 0 and len(answer) < 600
    else:
        behavior_correct = len(answer) > 100  # answered with substance

    # Citation count
    min_cit = spec.get("min_citations", 0)
    citation_ok = len(trace.citations) >= min_cit

    # Tool selection (soft check — did we use at least one expected tool?)
    expected_tools = spec.get("expected_tools", [])
    used_tools = {
        s.action["tool"]
        for s in trace.steps
        if s.action
    }
    tool_correct = (
        not expected_tools or bool(used_tools & set(expected_tools))
    )

    return {
        "required_facts_score": required_score,
        "required_facts_found": found,
        "required_facts_missing": [f for f in required if f not in found],
        "forbidden_violations": violations,
        "forbidden_ok": forbidden_ok,
        "behavior_correct": behavior_correct,
        "citation_ok": citation_ok,
        "citation_count": len(trace.citations),
        "tool_correct": tool_correct,
        "tools_used": list(used_tools),
        "overall_pass": all([
            required_score >= 0.5,
            forbidden_ok,
            behavior_correct,
            citation_ok,
        ]),
    }


def run_evals(ids: list[str] | None = None, category: str | None = None):
    RESULTS_DIR.mkdir(exist_ok=True)

    benchmark = json.loads(BENCHMARK.read_text())
    questions = benchmark["questions"]

    if ids:
        questions = [q for q in questions if q["id"] in ids]
    if category:
        questions = [q for q in questions if q["category"] == category]

    if not questions:
        print("No questions matched the filter.")
        return

    llm = LLMClient()
    registry = build_default_registry()
    tracer = Tracer()
    agent = ResearchAgent(llm, registry, tracer)

    results = []
    passed = 0

    for i, spec in enumerate(questions, 1):
        qid = spec["id"]
        question = spec["question"]
        print(f"\n[{i}/{len(questions)}] {qid}: {question[:70]}...")

        start = time.time()
        try:
            answer, trace = agent.run(question)
            scores = score_answer(answer, trace, spec)
            status = "PASS" if scores["overall_pass"] else "FAIL"
            if scores["overall_pass"]:
                passed += 1
        except Exception as exc:
            answer = f"ERROR: {exc}"
            trace = tracer.new_run(question)
            scores = {"overall_pass": False, "error": str(exc)}
            status = "ERROR"

        duration = time.time() - start
        print(f"  {status} | steps: {trace.total_steps} | {duration:.1f}s")
        if not scores.get("overall_pass"):
            if scores.get("required_facts_missing"):
                print(f"  Missing facts: {scores['required_facts_missing']}")
            if scores.get("forbidden_violations"):
                print(f"  Forbidden content: {scores['forbidden_violations']}")
            if not scores.get("behavior_correct"):
                print("  Behavior incorrect (should answer but didn't, or should refuse but answered)")

        result_entry = {
            "id": qid,
            "question": question,
            "category": spec["category"],
            "answer": answer,
            "citations": trace.citations,
            "scores": scores,
            "steps": trace.total_steps,
            "duration_seconds": duration,
            "run_id": trace.run_id,
        }
        results.append(result_entry)

    # Summary
    total = len(results)
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed ({100*passed//total}%)")
    print(f"\nBy category:")
    categories = {}
    for r in results:
        cat = r["category"]
        categories.setdefault(cat, {"pass": 0, "total": 0})
        categories[cat]["total"] += 1
        if r["scores"].get("overall_pass"):
            categories[cat]["pass"] += 1
    for cat, counts in sorted(categories.items()):
        print(f"  {cat:15s}: {counts['pass']}/{counts['total']}")

    # Save results
    output = {
        "benchmark_version": benchmark["version"],
        "total": total,
        "passed": passed,
        "pass_rate": passed / total if total else 0,
        "results": results,
    }
    out_path = RESULTS_DIR / f"eval_{int(time.time())}.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nFull results saved to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="+", help="Question IDs to run (e.g. q01 q07)")
    parser.add_argument("--category", help="Filter by category")
    args = parser.parse_args()
    run_evals(ids=args.ids, category=args.category)
