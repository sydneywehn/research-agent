"""Structured trace writer. Each run produces a JSON file in traces/."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TRACES_DIR = Path(__file__).parent.parent / "traces"
INDEX_FILE = TRACES_DIR / "index.jsonl"


@dataclass
class StepTrace:
    step: int
    thought: str
    action: dict | None        # {"tool": str, "query": str} or None for final
    observation: dict | None   # serialized ToolResult or None
    duration_seconds: float


@dataclass
class RunTrace:
    run_id: str
    question: str
    timestamp: str
    classifier: dict           # {scope, reason, domain}
    steps: list[StepTrace] = field(default_factory=list)
    final_answer: str = ""
    citations: list[str] = field(default_factory=list)
    total_steps: int = 0
    total_duration_seconds: float = 0.0
    error: str | None = None

    def add_step(self, step: StepTrace):
        self.steps.append(step)
        self.total_steps = len(self.steps)

    def finish(self, answer: str, citations: list[str], duration: float):
        self.final_answer = answer
        self.citations = citations
        self.total_duration_seconds = duration


class Tracer:
    def __init__(self):
        TRACES_DIR.mkdir(exist_ok=True)

    def new_run(self, question: str) -> RunTrace:
        return RunTrace(
            run_id=str(uuid.uuid4())[:8],
            question=question,
            timestamp=datetime.now(timezone.utc).isoformat(),
            classifier={},
        )

    def save(self, trace: RunTrace):
        TRACES_DIR.mkdir(exist_ok=True)
        path = TRACES_DIR / f"{trace.run_id}.json"

        # Convert dataclasses to dicts; ToolResult observations are already dicts
        data = asdict(trace)
        path.write_text(json.dumps(data, indent=2, default=str))

        # Append summary line to index
        index_entry = {
            "run_id": trace.run_id,
            "timestamp": trace.timestamp,
            "question": trace.question[:120],
            "scope": trace.classifier.get("scope"),
            "steps": trace.total_steps,
            "duration_seconds": trace.total_duration_seconds,
            "trace_file": str(path.name),
        }
        with INDEX_FILE.open("a") as f:
            f.write(json.dumps(index_entry) + "\n")

        return path
