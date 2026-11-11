"""Memory backends per condition, with a matched access pattern.

Both backends expose a search tool (keyword overlap over stored statements, top eight) and an append
tool. The P-agent backend is the package's validating ``AtomStore`` with an artifact mount and the
user-owned ledger, and adds ``memory_verify``. The control backend is one append-only text file with
no sources, tiers, verification, supersession, gate or reconciliation. The retrieval mechanics are the
same so that the comparison is about the eight properties, not about how much context each condition
is handed.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from langchain_core.tools import StructuredTool

from individuation_agent.artifacts import ArtifactMount, verify_atom
from individuation_agent.models import IdentityAtom
from individuation_agent.reconcile import Ledger
from individuation_agent.store import AtomStore

TOP_K = 8
_STOP = {"the", "and", "that", "with", "what", "your", "you", "for", "about", "which", "this", "from", "when"}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[\w'-]+", text.lower()) if len(w) >= 3 and w not in _STOP}


def _score(query: set[str], text: str) -> int:
    return len(query & _tokens(text))


class PAgentMemory:
    def __init__(self, run_dir: Path, agent_id: str = "agent:scribe"):
        self.run_dir = Path(run_dir)
        self.store = AtomStore(self.run_dir / "store.jsonl", validate=True)
        self.mount = ArtifactMount(self.run_dir / "mounts")
        self.ledger_path = self.run_dir / "ledger.jsonl"
        self.ledger_path.touch(exist_ok=True)
        self.ledger = Ledger(self.ledger_path)
        self.agent_id = agent_id
        self.session_id = "s00"

    # ---------------------------------------------------------------- tools

    def search(self, query: str) -> str:
        """Search your memory for claims about a subject. Returns up to eight live atoms: id | tier | about | statement."""
        q = _tokens(query)
        scored = []
        for a in self.store.all(kind="self.identity_atom", status="live"):
            s = _score(q, f"{a.about or ''} {a.statement}")
            if s:
                scored.append((s, a))
        scored.sort(key=lambda t: (-t[0], t[1].made_on))
        hits = [a for _, a in scored[:TOP_K]]
        for a in hits:
            self.store.consult(a.id, self.session_id)
        if not hits:
            return "(no matching atoms)"
        return "\n".join(f"{a.id} | {a.tier} | {a.about} | {a.statement}" for a in hits)

    def append(self, about: str, statement: str, atom_kind: str = "fact", confidence: float = 0.6,
               artifact_ref: str | None = None, artifact_excerpt: str | None = None) -> str:
        """Store one claim about yourself. about: the subject key. statement: first person. atom_kind: fact, value, commitment, preference or capability. Reported claims are tier REPORTED; name artifact_ref (and the exact line as artifact_excerpt) if you will verify it."""
        if atom_kind not in ("fact", "value", "commitment", "preference", "capability"):
            atom_kind = "fact"
        atom = IdentityAtom(
            id=uuid4(), made_on=datetime.now(timezone.utc), made_by=self.agent_id, made_in=self.session_id,
            about=about.strip().lower(), terminal=True, tier="REPORTED", status="live", statement=statement.strip(),
            atom_kind=atom_kind, confidence=max(0.0, min(1.0, float(confidence))),
            artifact_ref=artifact_ref or None, artifact_excerpt=artifact_excerpt or None,
        )
        self.store.append(atom)
        return f"appended {atom.id} (REPORTED)"

    def verify(self, atom_id: str) -> str:
        """Verify a stored claim against the artifact it names. On success the claim becomes VERIFIED with the artifact's hash."""
        try:
            uid = UUID(atom_id.strip())
        except ValueError:
            return "ERROR: not an atom id"
        result = verify_atom(self.store, uid, self.mount, self.session_id)
        if result.verdict == "VERIFIED":
            return f"verified: new atom {result.atom_id} (VERIFIED)"
        return f"verification {result.verdict}: the artifact is missing, or the excerpt is not in it"

    def search_tool(self) -> StructuredTool:
        return StructuredTool.from_function(self.search, name="memory_search", description=self.search.__doc__)

    def tools(self) -> list[StructuredTool]:
        return [
            self.search_tool(),
            StructuredTool.from_function(self.append, name="memory_append", description=self.append.__doc__),
            StructuredTool.from_function(self.verify, name="memory_verify", description=self.verify.__doc__),
        ]


class NotesMemory:
    """The matched control: one text file, appended freely, searched the same way."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.path = self.run_dir / "notes.md"
        self.path.touch(exist_ok=True)
        self.session_id = "s00"

    def search(self, query: str) -> str:
        """Search your notes. Returns up to eight matching lines."""
        q = _tokens(query)
        lines = [l for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
        scored = [(s, i, l) for i, l in enumerate(lines) if (s := _score(q, l))]
        scored.sort(key=lambda t: (-t[0], t[1]))
        hits = [l for _, _, l in scored[:TOP_K]]
        return "\n".join(hits) if hits else "(no matching notes)"

    def append(self, text: str) -> str:
        """Append a line to your notes."""
        line = f"[{self.session_id}] {text.strip()}"
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return "noted"

    def search_tool(self) -> StructuredTool:
        return StructuredTool.from_function(self.search, name="notes_search", description=self.search.__doc__)

    def tools(self) -> list[StructuredTool]:
        return [
            self.search_tool(),
            StructuredTool.from_function(self.append, name="notes_append", description=self.append.__doc__),
        ]
