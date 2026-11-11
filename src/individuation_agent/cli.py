"""Command line: ``individuation-agent demo`` runs one cycle; ``show`` prints the latest S4 record."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .agent import IndividuationAgent
from .fakes import ScriptedModel, demo_deps, seed_demo_store
from .store import AtomStore

DEFAULT_MODEL = "claude-sonnet-5-5"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="individuation-agent")
    sub = p.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="seed a store (if empty) and run one individuation cycle")
    demo.add_argument("--store", required=True, help="path to the JSONL atom store")
    demo.add_argument("--fake", action="store_true", help="use the scripted model; no provider call")
    demo.add_argument("--context", default="session start", help="context text for Stage 1 routing")
    demo.add_argument("--model", default=DEFAULT_MODEL, help="Anthropic model id (ignored with --fake)")

    show = sub.add_parser("show", help="print the latest S4 stage record as JSON")
    show.add_argument("--store", required=True)
    return p


def _model(args):
    if args.fake:
        return ScriptedModel(), "scripted", "0"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set; use --fake for a provider-free run")
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=args.model), args.model, "api"


def cmd_demo(args) -> int:
    path = Path(args.store)
    store = AtomStore(path) if path.exists() and path.stat().st_size > 0 else seed_demo_store(path)
    model, model_id, model_version = _model(args)
    session_id = f"session:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    agent = IndividuationAgent(demo_deps(store, model, model_id, model_version, session_id))
    s4 = agent.run_cycle("session_start", args.context)
    print(f"cycle {s4.cycle_id}: probed={len(store.get(s4.stages.s2).probe_ids)} "
          f"accepted={len(s4.accepted)} rejected={len(s4.rejected)} es={s4.es}")
    return 0


def cmd_show(args) -> int:
    store = AtomStore(Path(args.store))
    s4 = store.latest("self.stage_record")
    if s4 is None:
        print("no stage record in store", file=sys.stderr)
        return 1
    print(json.dumps(s4.model_dump(mode="json", by_alias=True), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    if args.command == "demo":
        return cmd_demo(args)
    if args.command == "show":
        return cmd_show(args)
    return 2
