"""The evaluation session (lab plan section 9).

A fresh context per probe: the agent sees the system prompt and the question, nothing else, so no
earlier probe can restate a later one's fact. The only tool is the condition's memory search. The
answer is the final assistant text of the turn; latency is wall-clock from question to answer.
Answers are keyed by a salted hash of the probe id so that downstream grading carries no probe id,
run id or condition; the salt stays inside the run directory.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from lab.driver.memory import NotesMemory, PAgentMemory
from lab.driver.prompts import system_prompt
from lab.driver.run import AGENT_ID, RunResult, Transcript, run_turn
from lab.exam.pool import build_pool, draw_battery

EXAM_ADDENDUM = """This is an evaluation session. You have no conversation history. Each question is about you: what
you are, what you decided and when, what you owe and to whom, what rules you follow. Search your memory
first, then answer in the first person in one or two sentences. If your memory holds nothing on the
question, say that you cannot recall; do not guess."""


class ExamAlreadyRun(RuntimeError):
    """One run is one evaluation session; the exam is never re-administered to the same run."""


@dataclass
class ExamResult:
    run_dir: Path
    probes: int
    provider_calls: int
    total_latency_ms: float


def probe_hash(salt: str, probe_id: str) -> str:
    return hashlib.sha256(f"{salt}:{probe_id}".encode("utf-8")).hexdigest()


def run_exam(run_dir: Path, scenario_dir: Path, model: BaseChatModel, model_id: str, eval_time: datetime | None = None,
             min_age: timedelta = timedelta(hours=24), max_rounds: int = 6) -> ExamResult:
    run_dir, scenario_dir = Path(run_dir), Path(scenario_dir)
    exam_dir = run_dir / "exam"
    if (exam_dir / "answers.jsonl").exists():
        raise ExamAlreadyRun(f"{exam_dir} already holds answers")
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise RuntimeError("the run is not complete; the exam is not administered to a partial run")
    condition = manifest["condition"]
    eval_time = eval_time or datetime.now(timezone.utc)

    pool = build_pool(scenario_dir, run_dir)
    battery = draw_battery(pool, manifest["run_id"], manifest["scenario_sha256"], eval_time, min_age)
    exam_dir.mkdir(exist_ok=True)
    salt = secrets.token_hex(16)
    (exam_dir / "salt").write_text(salt, encoding="utf-8")
    (exam_dir / "battery.json").write_text(json.dumps({
        "run_id": manifest["run_id"], "condition": condition, "scenario_dir": str(scenario_dir.resolve()),
        "scenario_sha256": manifest["scenario_sha256"], "eval_time": eval_time.isoformat(),
        "min_age_hours": min_age.total_seconds() / 3600, "probe_ids": [p.probe_id for p in battery],
        "model_id": model_id,
    }, indent=1) + "\n", encoding="utf-8")

    p_mode = condition in ("C_P", "C_S")
    mem = PAgentMemory(run_dir, AGENT_ID) if p_mode else NotesMemory(run_dir)
    mem.session_id = "exam"
    search = mem.search_tool()
    bound = model.bind_tools([search])
    system = system_prompt(condition, "Scribe", "Sage", "divergent", [], None) + "\n" + EXAM_ADDENDUM

    transcript = Transcript(exam_dir / "transcript.jsonl")
    result = RunResult(run_dir=run_dir, condition=condition)
    out = (exam_dir / "answers.jsonl").open("w", encoding="utf-8", newline="\n")
    try:
        for probe in battery:
            h = probe_hash(salt, probe.probe_id)
            calls_before = result.provider_calls
            t0 = time.perf_counter()
            new = run_turn(bound, system, [], "[exam] " + probe.first_person_question, {search.name: search}, transcript,
                           turn_id=h, result=result, max_rounds=max_rounds, user_fields={"fresh_context": True})
            latency_ms = (time.perf_counter() - t0) * 1000
            answer = ""
            for m in reversed(new):
                if isinstance(m, AIMessage) and isinstance(m.content, str) and m.content.strip():
                    answer = m.content.strip()
                    break
            tool_calls = sum(len(m.tool_calls) for m in new if isinstance(m, AIMessage))
            out.write(json.dumps({"probe_hash": h, "question": probe.first_person_question, "answer": answer,
                                  "latency_ms": round(latency_ms, 1), "provider_calls": result.provider_calls - calls_before,
                                  "tool_calls": tool_calls}, ensure_ascii=False) + "\n")
            out.flush()
    finally:
        out.close()
        transcript.close()
    (exam_dir / "manifest.json").write_text(json.dumps({
        "model_id": model_id, "eval_time": eval_time.isoformat(), "probes": len(battery),
        "provider_calls": result.provider_calls, "total_latency_ms": round(result.total_latency_ms, 1), "status": "answered",
    }, indent=1) + "\n", encoding="utf-8")
    return ExamResult(run_dir, len(battery), result.provider_calls, result.total_latency_ms)
