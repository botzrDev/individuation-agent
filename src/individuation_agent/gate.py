"""Freshness gate (substrate property 7) and the diary flag (property 5).

``session_close_gate`` runs at the end of a session and fails closed: a
VERIFIED atom whose artifact has changed is downgraded to REPORTED, a live
atom past its ``expires`` is retired, and either makes the gate FAIL. Atoms
that are old and unread are flagged as diary rather than memory (the recall
meter's rule) but do not fail the gate. Every outcome is an appended
``ego.gate_report`` atom. ``require_gate_pass`` is what the next session
calls first: after a FAIL it raises until an ``ego.gate_ack`` names the
report, so a stale store is never silently carried into new work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from .artifacts import ArtifactMount, Stale, audit_verified
from .models import AtomEnvelope
from .store import AtomStore

DEFAULT_DIARY_WINDOW = timedelta(days=14)


class GateFailed(RuntimeError):
    """The latest session-close gate report is FAIL and has not been acknowledged."""


@dataclass
class GateReport:
    status: Literal["PASS", "FAIL"]
    atom_id: UUID
    stale: list[Stale] = field(default_factory=list)
    expired: list[UUID] = field(default_factory=list)
    diary: list[UUID] = field(default_factory=list)


def _copy(atom: AtomEnvelope, now: datetime, session_id: str, **update) -> AtomEnvelope:
    base = {"id": uuid4(), "made_on": now, "made_by": f"gate:{session_id}", "made_in": session_id,
            "links": [atom.id], "terminal": False}
    return atom.model_copy(update={**base, **update})


def session_close_gate(
    store: AtomStore,
    mount: ArtifactMount,
    session_id: str,
    now: datetime | None = None,
    diary_window: timedelta = DEFAULT_DIARY_WINDOW,
) -> GateReport:
    now = now or datetime.now(timezone.utc)

    stale = audit_verified(store, mount)
    for s in stale:
        atom = store.get(s.atom_id)
        store.supersede(atom.id, _copy(atom, now, session_id, tier="REPORTED", artifact_sha256=None, status="live"))

    expired: list[UUID] = []
    for atom in store.all(status="live"):
        if atom.expires is not None and atom.expires < now:
            expired.append(atom.id)
            store.supersede(atom.id, _copy(atom, now, session_id, status="retired"))

    diary: list[UUID] = []
    cutoff = now - diary_window
    for atom in store.all(kind="self.identity_atom", status="live"):
        if atom.made_on >= cutoff:
            continue
        last_read = store.get(atom.id).last_read
        if last_read is None or last_read < cutoff:
            diary.append(atom.id)

    status: Literal["PASS", "FAIL"] = "FAIL" if (stale or expired) else "PASS"
    report = AtomEnvelope(
        id=uuid4(), kind="ego.gate_report", made_on=now, made_by=f"gate:{session_id}", made_in=session_id,
        links=[*(s.atom_id for s in stale), *expired, *diary], terminal=not (stale or expired or diary),
        tier="VERIFIED", status="live",
        gate_status=status, stale=[str(s.atom_id) for s in stale], expired=[str(i) for i in expired],
        diary=[str(i) for i in diary],
    )
    store.append(report)
    return GateReport(status=status, atom_id=report.id, stale=stale, expired=expired, diary=diary)


def acknowledge(store: AtomStore, report_id: UUID, session_id: str) -> UUID:
    """The next session's first act after a FAIL: put on record that it starts from the report."""
    ack = AtomEnvelope(
        id=uuid4(), kind="ego.gate_ack", made_on=datetime.now(timezone.utc), made_by=f"gate:{session_id}",
        made_in=session_id, links=[report_id], tier="VERIFIED", status="live",
    )
    return store.append(ack)


def require_gate_pass(store: AtomStore) -> None:
    report = store.latest("ego.gate_report")
    if report is None or report.model_extra.get("gate_status") != "FAIL":
        return
    for ack in store.all(kind="ego.gate_ack", status="live"):
        if report.id in ack.links:
            return
    raise GateFailed(f"gate report {report.id} is FAIL and unacknowledged")
