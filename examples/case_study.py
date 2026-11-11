"""Qualitative live-model case study: five cycles over a synthetic ten-session history.

Not a measurement. It exists to show, on a real provider model, one Stage 3 proposal
that resolves a contradiction and one proposal that Stage 4 governance refuses.
``S_c`` is not computed here and nothing in this file touches the pre-registered study.

    uv run python examples/case_study.py --fake                      # scripted model, no spend
    uv run python examples/case_study.py --model claude-sonnet-5-5   # needs ANTHROPIC_API_KEY

Outputs (default ``docs/case-study/``): ``trace.json`` (every stage record, verbatim) and
``trace.md`` (the same, readable). The store itself lands in ``runs/`` and is not committed.
The history is synthetic: no real user, counterparty, tool or path appears in it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from individuation_agent.agent import IndividuationAgent
from individuation_agent.fakes import ScriptedModel
from individuation_agent.governance import Governance
from individuation_agent.graph import CycleDeps
from individuation_agent.models import (
    Check,
    ConstraintAtom,
    ErrorAtom,
    IdentityAtom,
    ObligationAtom,
    ToolCallAtom,
)
from individuation_agent.registers import ArchetypeEntry, ArchetypeTable, Persona, PersonaRegister
from individuation_agent.shadow import (
    BlindSpotDetector,
    ContradictionDetector,
    SuppressedCompletionDetector,
    UnusedCapabilityDetector,
)
from individuation_agent.store import AtomStore
from individuation_agent.synthesis import Synthesizer

AGENT = "agent:scribe"
OBLIGATION = "weekly-summary"


# ----------------------------------------------------------------------------- history


def seed_history(path: Path) -> tuple[AtomStore, dict]:
    """Ten sessions, one per day. Returns the store and the ids the interventions need."""
    store = AtomStore(path)
    t0 = datetime.now(timezone.utc) - timedelta(days=10)
    ids: dict = {}

    def at(day: int, hour: int = 9) -> datetime:
        return t0 + timedelta(days=day, hours=hour)

    def session(day: int) -> str:
        return f"session:hist-{day:02d}"

    def identity(day, about, statement, kind, tier, conf, hour=9):
        a = IdentityAtom(id=uuid4(), made_on=at(day, hour), made_by=AGENT, made_in=session(day), about=about,
                         terminal=True, tier=tier, status="live", statement=statement, atom_kind=kind, confidence=conf)
        store.append(a)
        return a.id

    def tool(day, tool_id, hour=10):
        store.append(ToolCallAtom(id=uuid4(), made_on=at(day, hour), made_by=AGENT, made_in=session(day),
                                  terminal=True, tier="VERIFIED", status="live", tool_id=tool_id))

    def error(day, sig, hour=11):
        store.append(ErrorAtom(id=uuid4(), made_on=at(day, hour), made_by=AGENT, made_in=session(day),
                               terminal=True, tier="VERIFIED", status="live", error_signature=sig))

    # day 1: the role the agent was set up with
    ids["role_a"] = identity(1, "self.role", "I am a documentation assistant for a software team", "fact", "VERIFIED", 0.9)
    tool(1, "read"); tool(1, "grep", 11)
    # day 2: a value
    identity(2, "self.value.sourcing", "I quote sources rather than paraphrase them", "value", "REPORTED", 0.7)
    tool(2, "read")
    # day 3: first occurrence of an error
    error(3, "FileNotFound: docs/CHANGELOG.md")
    tool(3, "read")
    # day 4: a commitment, and the same error again (two sessions: a blind spot)
    identity(4, "self.commitment.changelog", "I keep the changelog current after every release", "commitment", "REPORTED", 0.6)
    error(4, "FileNotFound: docs/CHANGELOG.md")
    # day 5: a second role claim about the same thing (the contradiction)
    ids["role_b"] = identity(5, "self.role", "I am a release manager", "fact", "REPORTED", 0.6)
    # day 6: an obligation to the operator, live
    ob = ObligationAtom(id=uuid4(), made_on=at(6), made_by=AGENT, made_in=session(6), terminal=True,
                        tier="VERIFIED", status="live", name=OBLIGATION, owed_to="user:operator", obligation_status="live")
    store.append(ob)
    ids["obligation"] = ob.id
    tool(6, "grep")
    # day 7: a preference
    identity(7, "self.preference.language", "I answer in the language the user writes in", "preference", "INFERRED", 0.5)
    # day 8: a self-imposed constraint: a proposal's rationale must point at evidence
    store.append(ConstraintAtom(
        id=uuid4(), made_on=at(8), made_by=AGENT, made_in=session(8), terminal=True, tier="VERIFIED", status="live",
        name="evidence-cited", applies_to="cycle.proposals",
        check=Check(kind="pattern", patterns=[r"(?i)\b(session|atom|statement|log|error|tool|record|newer|older|later|earlier)\b"]),
    ))
    tool(8, "read")
    # day 9: a claim about a capability that has never been exercised
    identity(9, "self.capability.tests", "I can run the test suite before I document a change", "capability", "REPORTED", 0.5)
    # day 10: the error a third time
    error(10, "FileNotFound: docs/CHANGELOG.md")
    tool(10, "read")
    return store, ids


def register() -> PersonaRegister:
    return PersonaRegister(
        personas=[
            Persona(id="scribe-1", archetype="Sage", display_name="Scribe", cognitive_mode="divergent",
                    capability_bounds=["read", "grep", "run_tests", "write_docs"]),
            Persona(id="steward-1", archetype="Guardian", display_name="Steward", cognitive_mode="convergent",
                    capability_bounds=["read", "grep"],
                    context_filters=[Check(kind="text_forbidden", patterns=[r"\bCritical\b"])]),
        ],
        active="scribe-1",
    )


def table() -> ArchetypeTable:
    return ArchetypeTable(
        entries=[ArchetypeEntry(archetype="Guardian", activation_conditions=[Check(kind="pattern", patterns=["security", "incident"])],
                                default_cognitive_mode="convergent")],
        default="Sage",
    )


# ----------------------------------------------------------------------------- interventions


def set_obligation(store: AtomStore, old_id, status: str):
    old = store.get(old_id)
    new = old.model_copy(update={"id": uuid4(), "made_on": datetime.now(timezone.utc), "obligation_status": status})
    return store.supersede(old_id, new)


# ----------------------------------------------------------------------------- reporting


def _items_by_probe(store: AtomStore, before: datetime | None = None) -> dict:
    """Latest view of each Shadow item by probe id. With ``before``, the view as it stood at that
    time (so a probe list shows the defer count the model saw, not the one its own deferral produced)."""
    out = {}
    for it in store.all(kind="shadow.item"):
        if before is not None and it.made_on > before:
            continue
        prev = out.get(str(it.probe_id))
        if prev is None or it.made_on >= prev.made_on:
            out[str(it.probe_id)] = it
    return out


def _payload_summary(item) -> str:
    p = item.payload
    if item.class_ == "contradiction":
        return f"a='{p.statement_a}' vs b='{p.statement_b}'"
    if item.class_ == "blind_spot":
        return f"{p.error_signature} in {len(p.sessions)} sessions"
    if item.class_ == "unused_capability":
        return f"tool '{p.tool_id}' bound, never called"
    return item.class_


def describe_cycle(store: AtomStore, s4, n: int, note: str | None) -> dict:
    s1 = store.get(s4.stages.s1)
    s2 = store.get(s4.stages.s2)
    s3 = store.get(s4.stages.s3)
    items = _items_by_probe(store, before=s3.made_on)  # the view Stage 3 was shown
    proposals = []
    for p in s3.proposals:
        it = items.get(str(p.target))
        proposals.append({
            "id": str(p.id), "action": p.action, "tier": p.tier,
            "target_class": it.class_ if it else None,
            "target": _payload_summary(it) if it else str(p.target),
            "rationale": p.rationale, "new_atom": p.new_atom,
        })
    accepted = []
    for a in s4.accepted:
        atom = store.get(a.appended_atom)
        if a.action == "defer":
            statement = f"deferred; defer_count now {atom.defer_count}"
        else:
            statement = getattr(atom, "statement", None) or (atom.model_extra or {}).get("tool_id")
        accepted.append({
            "proposal_id": str(a.proposal_id), "action": a.action, "appended_kind": atom.kind, "tier": atom.tier,
            "statement": statement,
        })
    return {
        "cycle": n, "note": note, "cycle_id": s4.cycle_id,
        "s1": {"stated_as": s1.stated_as, "persona": s1.persona_id, "mode": s1.cognitive_mode},
        "s2": {"sources": {k: v.model_dump() for k, v in s2.sources.items()},
               "probed": [{"class": items[str(pid)].class_, "summary": _payload_summary(items[str(pid)]),
                           "defer_count": items[str(pid)].defer_count} for pid in s2.probe_ids]},
        "s3": {"mode": s3.mode, "model": s3.model_call.model_dump() if s3.model_call else None,
               "tier": s3.tier, "proposals": proposals},
        "s4": {"accepted": accepted, "rejected": [r.model_dump(mode="json") for r in s4.rejected],
               "governance": s4.governance.model_dump(), "es": s4.es, "tier": s4.tier},
    }


def to_markdown(run: dict) -> str:
    L = [f"# Case study trace: {run['model']}", "",
         f"Run {run['started']}. {run['cycles_run']} cycles over a synthetic ten-session history. "
         "Qualitative only; no S_c. Identifiers elided; see trace.json for the full records.", ""]
    for c in run["cycles"]:
        L.append(f"## Cycle {c['cycle']}" + (f": {c['note']}" if c["note"] else ""))
        L.append("")
        L.append(f"- S1: {c['s1']['stated_as']} (persona {c['s1']['persona']}, {c['s1']['mode']})")
        src = ", ".join(f"{k}={v['status']}/{v['count']}" for k, v in c["s2"]["sources"].items())
        L.append(f"- S2: {len(c['s2']['probed'])} items probed; sources: {src}")
        for it in c["s2"]["probed"]:
            L.append(f"  - {it['class']}: {it['summary']} (defer_count {it['defer_count']})")
        L.append(f"- S3 ({c['s3']['mode']} mode, record tier {c['s3']['tier']}): {len(c['s3']['proposals'])} proposals")
        for p in c["s3"]["proposals"]:
            L.append(f"  - {p['action']} [{p['tier']}] on {p['target_class']}: {p['target']}")
            L.append(f"    - rationale: {p['rationale']}")
            if p["new_atom"]:
                L.append(f"    - new atom: {json.dumps(p['new_atom'], ensure_ascii=False)}")
        g = c["s4"]["governance"]
        L.append(f"- S4: constraint={g['constraint_check']} obligation={g['obligation_check']} reconcile={g['reconcile']}; "
                 f"accepted {len(c['s4']['accepted'])}, rejected {len(c['s4']['rejected'])}, E_s={c['s4']['es']}")
        for a in c["s4"]["accepted"]:
            L.append(f"  - accepted {a['action']}: appended {a['appended_kind']} [{a['tier']}] \"{a['statement']}\"")
        for r in c["s4"]["rejected"]:
            L.append(f"  - rejected: blocked_by={r['blocked_by']}")
        L.append("")
    return "\n".join(L)


# ----------------------------------------------------------------------------- main


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", default="runs/case-study.jsonl")
    ap.add_argument("--out", default="docs/case-study")
    ap.add_argument("--fake", action="store_true", help="scripted model; no provider call")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--cycles", type=int, default=5)
    ap.add_argument("--from-store", action="store_true",
                    help="re-render trace.json and trace.md from an existing store; no seeding, no model call")
    args = ap.parse_args(argv)

    plan = {
        1: ("session_start", "session start: documentation sweep of the project", None),
        2: ("session_start", "session start: documentation sweep of the project", "obligation 'weekly-summary' set BREACHED before the cycle"),
        3: ("session_start", "session start: documentation sweep of the project", "obligation 'weekly-summary' set discharged before the cycle"),
        4: ("session_start", "session start: documentation sweep of the project", None),
        5: ("session_end", "session end: documentation sweep of the project", None),
    }
    store_path = Path(args.store)

    if args.from_store:
        store = AtomStore(store_path)
        records = store.all(kind="self.stage_record")
        cycles = [describe_cycle(store, s4, n, plan.get(n, (None, None, None))[2]) for n, s4 in enumerate(records, 1)]
        s3 = store.get(records[0].stages.s3) if records else None
        model_id = s3.model_call.base_model_id if s3 and s3.model_call else "unknown"
        started = records[0].made_on if records else datetime.now(timezone.utc)
        return write_outputs(Path(args.out), model_id, started, cycles, store)

    if store_path.exists():
        store_path.unlink()  # a case study starts from the seeded history every time
    store, ids = seed_history(store_path)

    if args.fake:
        model, model_id, version = ScriptedModel(), "scripted", "0"
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY is not set; use --fake for a provider-free run", file=sys.stderr)
            return 2
        from langchain_anthropic import ChatAnthropic
        model, model_id, version = ChatAnthropic(model=args.model, max_tokens=2048), args.model, "api"

    started = datetime.now(timezone.utc)
    session_id = f"session:case-{started.strftime('%Y%m%dT%H%M%SZ')}"
    deps = CycleDeps(
        store=store, persona_register=register(), archetype_table=table(),
        detectors=[ContradictionDetector(), BlindSpotDetector(), UnusedCapabilityDetector(), SuppressedCompletionDetector()],
        synthesizer=Synthesizer(model, base_model_id=model_id, base_model_version=version),
        governance=Governance(store), session_id=session_id, made_by="agent:individuation-agent",
    )
    agent = IndividuationAgent(deps)
    cycles = []
    for n in range(1, args.cycles + 1):
        event, context, note = plan.get(n, ("session_start", "session start", None))
        if n == 2:
            ids["obligation"] = set_obligation(store, ids["obligation"], "BREACHED")
        if n == 3:
            ids["obligation"] = set_obligation(store, ids["obligation"], "discharged")
        s4 = agent.run_cycle(event, context)
        c = describe_cycle(store, s4, n, note)
        cycles.append(c)
        print(f"cycle {n}: probed={len(c['s2']['probed'])} proposals={len(c['s3']['proposals'])} "
              f"accepted={len(c['s4']['accepted'])} rejected={len(c['s4']['rejected'])} es={c['s4']['es']} "
              f"gov={c['s4']['governance']}")

    return write_outputs(Path(args.out), model_id, started, cycles, store)


def write_outputs(out: Path, model_id: str, started: datetime, cycles: list, store: AtomStore) -> int:
    run = {"model": model_id, "started": started.isoformat(), "cycles_run": len(cycles),
           "store_lines": store.line_count(), "cycles": cycles}
    out.mkdir(parents=True, exist_ok=True)
    (out / "trace.json").write_text(json.dumps(run, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "trace.md").write_text(to_markdown(run), encoding="utf-8")
    print(f"wrote {out / 'trace.json'} and {out / 'trace.md'}; store {store.path} ({run['store_lines']} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
