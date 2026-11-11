"""Seed a demo store from the command line: ``uv run python examples/seed_store.py runs/demo.jsonl``."""

import sys
from pathlib import Path

from individuation_agent.fakes import seed_demo_store

if __name__ == "__main__":
    seed_demo_store(Path(sys.argv[1] if len(sys.argv) > 1 else "runs/demo.jsonl"))
