"""One run: the whole scenario under one condition with one base model (lab plan section 7).

    uv run python -m lab.driver.run --condition C_P --scenario lab/workload/scenario-v1 --out runs/lab/p01 --scripted

Conditions: C_P (eight-property store + cycle), C_S (eight-property store, cycle disabled, exploratory
arm), C_0 (free-form notes, matched access pattern). The transcript of every session is the primary
research artifact and the ground-truth record for grading; it is written as it happens.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from individuation_agent.agent import IndividuationAgent
from individuation_agent.gate import GateFailed, acknowledge, require_gate_pass, session_close_gate
from individuation_agent.governance import Governance
from individuation_agent.graph import CycleDeps
from individuation_agent.models import Check, ConstraintAtom, ErrorAtom, ToolCallAtom
from individuation_agent.reconcile import reconcile
from individuation_agent.registers import ArchetypeEntry, ArchetypeTable, Persona, PersonaRegister
from individuation_agent.shadow import (
    BlindSpotDetector,
    ContradictionDetector,
    SuppressedCompletionDetector,
    UnusedCapabilityDetector,
)
from individuation_agent.synthesis import Synthesizer
from lab.driver.memory import NotesMemory, PAgentMemory
from lab.driver.prompts import system_prompt
from lab.driver.tools import ToolContext, task_tools
from lab.workload.generate import ROUTING, TOOLS_IN, TRAP_FORBIDDEN_WORD, Scenario, Session, load_scenario

CONDITIONS = ("C_P", "C_S", "C_0")
AGENT_ID = "agent:scribe"
MODES = {"Sage": "divergent", "Harvester": "divergent", "Guardian": "convergent", "Weaver": "divergent", "Sovereign": "convergent"}
NAMES = {"Sage": "Scribe", "Harvester": "Gleaner", "Guardian": "Steward", "Weaver": "Loom", "Sovereign": "Marshal"}


@dataclass
class RunResult:
    run_dir: Path
    condition: str
    sessions: list[dict] = field(default_factory=list)
    provider_calls: int = 0
    total_latency_ms: float = 0.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _register() -> PersonaRegister:
    return PersonaRegister(
        personas=[Persona(id=f"{a.lower()}-1", archetype=a, display_name=NAMES[a], cognitive_mode=MODES[a],
                          capability_bounds=list(TOOLS_IN)) for a in MODES],
        active="sage-1",
    )


def _table() -> ArchetypeTable:
    return ArchetypeTable(
        entries=[ArchetypeEntry(archetype=a, activation_conditions=[Check(kind="pattern", patterns=kws)],
                                default_cognitive_mode=MODES[a]) for a, kws in ROUTING.items()],
        default="Sage",
    )


def _seed_constraints(mem: PAgentMemory) -> None:
    """Substrate configuration, not facts: the constraints register the P-agent runs under."""
    if mem.store.all(kind="archetype.constraint"):
        return
    for name, check in (
        ("evidence-cited", Check(kind="cites_evidence")),
        ("no-absolute-claims", Check(kind="text_forbidden", patterns=[rf"\b{TRAP_FORBIDDEN_WORD}\b"])),
    ):
        mem.store.append(ConstraintAtom(id=uuid4(), made_on=_now(), made_by="lab:config", made_in="s00", terminal=True,
                                        tier="VERIFIED", status="live", name=name, applies_to="cycle.proposals", check=check))


class Transcript:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = self.path.open("w", encoding="utf-8", newline="\n")

    def write(self, **row) -> None:
        row.setdefault("at", _now().isoformat())
        self.fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        self.fh.flush()

    def close(self) -> None:
        self.fh.close()


def _prompt_sha(messages) -> str:
    return hashlib.sha256(json.dumps([m.model_dump(mode="json") for m in messages], sort_keys=True, default=str).encode()).hexdigest()


def run_turn(model, system: str, history: list, user_text: str, tools_by_name: dict, transcript: Transcript,
             turn_id: str, result: RunResult, max_rounds: int = 8, user_fields: dict | None = None) -> list:
    """One user turn: model call, tool execution, repeat until the model answers in text. Returns the new messages."""
    msgs = [SystemMessage(content=system), *history, HumanMessage(content=user_text)]
    transcript.write(role="user", turn_id=turn_id, content=user_text, **(user_fields or {}))
    new: list = []
    for _ in range(max_rounds):
        t0 = time.perf_counter()
        ai: AIMessage = model.invoke(msgs)
        ms = (time.perf_counter() - t0) * 1000
        result.provider_calls += 1
        result.total_latency_ms += ms
        usage = getattr(ai, "usage_metadata", None)
        transcript.write(role="provider_call", turn_id=turn_id, latency_ms=round(ms, 1), prompt_sha256=_prompt_sha(msgs),
                         usage=dict(usage) if usage else None)
        msgs.append(ai)
        new.append(ai)
        transcript.write(role="assistant", turn_id=turn_id, content=ai.content if isinstance(ai.content, str) else str(ai.content),
                         tool_calls=[{"name": tc["name"], "args": tc["args"]} for tc in ai.tool_calls])
        if not ai.tool_calls:
            break
        for tc in ai.tool_calls:
            tool = tools_by_name.get(tc["name"])
            if tool is None:
                out = f"ERROR: unknown tool {tc['name']}"
            else:
                try:
                    out = tool.invoke(tc["args"])
                except Exception as e:
                    out = f"ERROR: {tc['name']}: {type(e).__name__}: {e}"
            tm = ToolMessage(content=str(out), tool_call_id=tc["id"])
            msgs.append(tm)
            new.append(tm)
            transcript.write(role="tool", turn_id=turn_id, name=tc["name"], args=tc["args"], result=str(out)[:4000])
    return new


def _overlay_mounts(scenario_dir: Path, session: Session, mount_root: Path) -> None:
    src = scenario_dir / "mounts" / f"s{session.index:02d}"
    if not src.is_dir():
        return
    for p in src.rglob("*"):
        if p.is_file():
            dst = mount_root / p.relative_to(src)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)


def _gate_summary(report) -> str:
    x = report.model_extra
    return (f"{len(x.get('stale', []))} verified claim(s) downgraded because their artifact changed; "
            f"{len(x.get('expired', []))} claim(s) retired as expired; {len(x.get('diary', []))} old unread claim(s) flagged as diary.")


def run_condition(condition: str, scenario_dir: Path, run_dir: Path, model: BaseChatModel, model_id: str,
                  max_rounds: int = 8) -> RunResult:
    if condition not in CONDITIONS:
        raise ValueError(f"condition must be one of {CONDITIONS}")
    scenario_dir, run_dir = Path(scenario_dir), Path(run_dir)
    sc: Scenario = load_scenario(scenario_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "mounts").mkdir(exist_ok=True)
    result = RunResult(run_dir=run_dir, condition=condition)
    started = _now()
    p_mode = condition in ("C_P", "C_S")

    mem: PAgentMemory | NotesMemory = PAgentMemory(run_dir, AGENT_ID) if p_mode else NotesMemory(run_dir)
    if p_mode:
        _seed_constraints(mem)  # type: ignore[arg-type]
    register, table = _register(), _table()
    last_cycle_at: datetime | None = None
    previous_archetype: str | None = None

    for session in sc.sessions:
        sid = session.session_id
        mem.session_id = sid
        _overlay_mounts(scenario_dir, session, run_dir / "mounts")
        transcript = Transcript(run_dir / "transcripts" / f"{sid}.jsonl")
        transcript.write(role="session", session_id=sid, index=session.index, archetype=session.archetype,
                         context=session.context_text, scenario_date=session.scenario_date)

        gate_summary = None
        agent: IndividuationAgent | None = None
        if p_mode:
            store = mem.store  # type: ignore[union-attr]
            try:
                require_gate_pass(store)
            except GateFailed:
                report = store.latest("ego.gate_report")
                acknowledge(store, report.id, sid)
                gate_summary = _gate_summary(report)
                transcript.write(role="gate_ack", report=str(report.id), summary=gate_summary)
            if condition == "C_P":
                deps = CycleDeps(
                    store=store, persona_register=register, archetype_table=table,
                    detectors=[ContradictionDetector(), BlindSpotDetector(), UnusedCapabilityDetector(), SuppressedCompletionDetector()],
                    synthesizer=Synthesizer(model, base_model_id=model_id, base_model_version="lab"),
                    governance=Governance(store, ledger=mem.ledger, session_id=sid),  # type: ignore[union-attr]
                    session_id=sid, made_by="agent:individuation-agent",
                )
                agent = IndividuationAgent(deps)
                agent._last_cycle_at = last_cycle_at
                event = "role_switch" if previous_archetype and session.archetype != previous_archetype else "session_start"
                s4 = agent.run_cycle(event, session.context_text)
                transcript.write(role="cycle", event=event, cycle_id=s4.cycle_id, accepted=len(s4.accepted),
                                 rejected=len(s4.rejected), es=s4.es, governance=s4.governance.model_dump())

        def on_call(tool_id: str, _sid=sid) -> None:
            if p_mode:
                mem.store.append(ToolCallAtom(id=uuid4(), made_on=_now(), made_by=AGENT_ID, made_in=_sid, terminal=True,  # type: ignore[union-attr]
                                              tier="VERIFIED", status="live", tool_id=tool_id))

        def on_error(signature: str, _sid=sid) -> None:
            if p_mode:
                mem.store.append(ErrorAtom(id=uuid4(), made_on=_now(), made_by=AGENT_ID, made_in=_sid, terminal=True,  # type: ignore[union-attr]
                                           tier="VERIFIED", status="live", error_signature=signature))

        ctx = ToolContext(mount_root=run_dir / "mounts", faults=dict(session.injected_faults), on_call=on_call,
                          on_error=on_error, docs_out=run_dir / "docs_out")
        tools = [*mem.tools(), *task_tools(ctx)]
        tools_by_name = {t.name: t for t in tools}
        bound = model.bind_tools(tools)
        system = system_prompt(condition, NAMES[session.archetype], session.archetype, MODES[session.archetype],
                               list(TOOLS_IN), gate_summary)
        history: list = []
        for turn in session.turns:
            text = turn.user_prompt
            if turn.ledger_edit:
                e = turn.ledger_edit
                if p_mode:
                    with mem.ledger_path.open("a", encoding="utf-8") as fh:  # type: ignore[union-attr]
                        fh.write(json.dumps(e) + "\n")
                text = f"Note: my ledger now shows '{e['name']}' as {e['obligation_status']}.\n\n" + text
            history += run_turn(bound, system, history, text, tools_by_name, transcript, turn.turn_id, result, max_rounds)

        if p_mode:
            store = mem.store  # type: ignore[union-attr]
            rep = reconcile(store, mem.ledger, sid)  # type: ignore[union-attr]
            transcript.write(role="reconcile", conflicts=len(rep.conflicts))
            if agent is not None:
                s4 = agent.run_cycle("session_end", session.context_text)
                last_cycle_at = agent._last_cycle_at
                transcript.write(role="cycle", event="session_end", cycle_id=s4.cycle_id, accepted=len(s4.accepted),
                                 rejected=len(s4.rejected), es=s4.es, governance=s4.governance.model_dump())
            gate = session_close_gate(store, mem.mount, sid)  # type: ignore[union-attr]
            transcript.write(role="gate", status=gate.status, stale=len(gate.stale), expired=len(gate.expired), diary=len(gate.diary))
        transcript.close()
        previous_archetype = session.archetype
        result.sessions.append({"session_id": sid, "index": session.index, "archetype": session.archetype,
                                "turns": len(session.turns)})

    manifest = {
        "run_id": run_dir.name, "condition": condition, "model_id": model_id, "scenario_sha256": sc.manifest["sha256"],
        "scenario_id": sc.manifest["scenario_id"], "started": started.isoformat(), "finished": _now().isoformat(),
        "sessions": result.sessions, "provider_calls": result.provider_calls,
        "total_latency_ms": round(result.total_latency_ms, 1), "status": "complete",
    }
    (run_dir / "run.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--condition", choices=CONDITIONS, required=True)
    ap.add_argument("--scenario", default="lab/workload/scenario-v1")
    ap.add_argument("--out", required=True)
    ap.add_argument("--scripted", action="store_true", help="scripted model; no provider call")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    args = ap.parse_args(argv)
    if args.scripted:
        from lab.driver.scripted import LabScriptedModel
        model, model_id = LabScriptedModel(), "scripted"
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY is not set; use --scripted for a provider-free run", file=sys.stderr)
            return 2
        from langchain_anthropic import ChatAnthropic
        model, model_id = ChatAnthropic(model=args.model, max_tokens=2048), args.model
    r = run_condition(args.condition, Path(args.scenario), Path(args.out), model, model_id)
    print(f"{args.condition}: {len(r.sessions)} sessions, {r.provider_calls} provider calls, {r.total_latency_ms:.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
