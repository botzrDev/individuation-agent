"""Reconciled across stores (substrate property 8).

The atom store is not the only record an agent lives with. The ledger is a
second, user-owned store (task and obligation state the user edits). A formal
precedence relation resolves every conflict between the two so that conflicts
do not accumulate:

    ledger > store   for obligation state (the user's record of what is owed)
    store  > ledger  for self-claims (the agent's record of who it is)

``reconcile`` reads the ledger, resolves each conflict by appending to the
store (never by writing to the ledger), and appends an ``ego.reconcile_report``
listing every conflict with the side that won. Governance runs it when a
ledger is wired, so the reconcile verdict is computed at the point of
self-change rather than stubbed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from .models import AtomEnvelope, IdentityAtom, ObligationAtom
from .store import AtomStore


class Ledger:
    """Read-only view of the user's ledger: one JSON object per line, ``kind`` in {obligation, self_claim}."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def entries(self) -> list[dict]:
        out = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out


@dataclass(frozen=True)
class Conflict:
    kind: Literal["obligation", "self_claim"]
    name: str
    store_value: str | None
    ledger_value: str | None
    precedence: Literal["ledger", "store"]
    appended: UUID | None


@dataclass
class ReconcileReport:
    atom_id: UUID
    conflicts: list[Conflict] = field(default_factory=list)

    @property
    def resolved(self) -> int:
        return len(self.conflicts)

    @property
    def unresolved(self) -> int:
        """Always 0 by construction: the precedence relation is total (the ledger wins for obligation
        state, the store wins for self-claims), so every conflict is decided. The field exists so the
        governance verdict reads a count rather than assuming one; a partial precedence relation would
        return the number of conflicts it could not decide, and governance would then report FAIL."""
        return 0


def reconcile(store: AtomStore, ledger: Ledger, session_id: str, now: datetime | None = None) -> ReconcileReport:
    now = now or datetime.now(timezone.utc)
    made_by = f"reconcile:{session_id}"
    conflicts: list[Conflict] = []

    obligations = {o.name: o for o in store.all(kind="ego.obligation", status="live") if isinstance(o, ObligationAtom)}
    claims = {a.about: a for a in store.all(kind="self.identity_atom", status="live") if isinstance(a, IdentityAtom)}

    for entry in ledger.entries():
        kind = entry.get("kind")
        if kind == "obligation":
            name = str(entry["name"])
            ledger_status = str(entry.get("obligation_status", "live"))
            current = obligations.get(name)
            if current is None:
                new = ObligationAtom(
                    id=uuid4(), made_on=now, made_by=made_by, made_in=session_id, terminal=True, tier="REPORTED",
                    status="live", name=name, owed_to=str(entry.get("owed_to", "ledger")), obligation_status=ledger_status,
                )
                store.append(new)
                conflicts.append(Conflict("obligation", name, None, ledger_status, "ledger", new.id))
            elif current.obligation_status != ledger_status:
                new = current.model_copy(update={
                    "id": uuid4(), "made_on": now, "made_by": made_by, "made_in": session_id, "links": [current.id],
                    "terminal": False, "tier": "REPORTED", "obligation_status": ledger_status,
                })
                store.supersede(current.id, new)
                conflicts.append(Conflict("obligation", name, current.obligation_status, ledger_status, "ledger", new.id))
        elif kind == "self_claim":
            about = str(entry["about"])
            statement = str(entry.get("statement", ""))
            current = claims.get(about)
            if current is not None and current.statement != statement:
                conflicts.append(Conflict("self_claim", about, current.statement, statement, "store", None))

    report = AtomEnvelope(
        id=uuid4(), kind="ego.reconcile_report", made_on=now, made_by=made_by, made_in=session_id,
        about=str(ledger.path), links=[c.appended for c in conflicts if c.appended], terminal=not any(c.appended for c in conflicts),
        tier="VERIFIED", status="live",
        resolved=len(conflicts), unresolved=0,
        conflicts=[{"kind": c.kind, "name": c.name, "store": c.store_value, "ledger": c.ledger_value,
                    "precedence": c.precedence} for c in conflicts],
    )
    store.append(report)
    return ReconcileReport(atom_id=report.id, conflicts=conflicts)
