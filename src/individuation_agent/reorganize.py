"""Stage 4 application: turn accepted proposals into appended atoms.

Every action appends; the only "edits" are superseded copies appended next
to a replacement. The Shadow item that a proposal targets is itself
superseded by a copy carrying the resolution. Governance has already
checked that resolve/revise proposals carry a valid ``new_atom``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from .models import Accepted, AtomEnvelope, ContradictionPayload, IdentityAtom, Proposal, Resolution, ShadowItem
from .store import AtomStore


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mark_item(store: AtomStore, item: ShadowItem, action: str, by_atom: UUID | None, cycle_id: str,
               bump_defer: bool = False) -> UUID:
    """Supersede ``item`` with a copy carrying the resolution; returns the copy's id (used as by_atom for defer)."""
    new_id = uuid4()
    updated = item.model_copy(
        update={
            "id": new_id,
            "made_on": _now(),
            "defer_count": item.defer_count + (1 if bump_defer else 0),
            "resolution": Resolution(cycle_id=cycle_id, action=action, by_atom=by_atom or new_id),
        }
    )
    store.supersede(item.id, updated)
    return new_id


def _identity_from(p: Proposal, about: str | None, atom_kind: str, session_id: str, made_by: str,
                   links: list[UUID], supersedes: UUID | None) -> IdentityAtom:
    new = p.new_atom or {}
    return IdentityAtom(
        id=uuid4(),
        made_on=_now(),
        made_by=made_by,
        made_in=session_id,
        about=new.get("about", about),
        links=links,
        terminal=not links,
        supersedes=supersedes,
        tier=p.tier,
        status="live",
        statement=str(new.get("statement", p.rationale)),
        atom_kind=new.get("atom_kind", atom_kind),
        confidence=float(new.get("confidence", 0.5)),
    )


def apply(
    store: AtomStore,
    accepted: list[Proposal],
    items_by_id: dict[UUID, ShadowItem],
    persona_id: str,
    cycle_id: str,
    session_id: str,
) -> list[Accepted]:
    made_by = f"stage4:{session_id}"
    out: list[Accepted] = []
    for p in accepted:
        item = items_by_id[p.target]

        if p.action == "resolve":
            about, links, supersedes = None, [item.id], None
            if isinstance(item.payload, ContradictionPayload):
                about = store.get(item.payload.atom_a).about
                links = [item.payload.atom_a, item.payload.atom_b]
                supersedes = item.payload.atom_a
            new = _identity_from(p, about, "fact", session_id, made_by, links, supersedes)
            store.append(new)
            if isinstance(item.payload, ContradictionPayload):
                store.mark_superseded(item.payload.atom_a)
                store.mark_superseded(item.payload.atom_b)
            _mark_item(store, item, "resolve", new.id, cycle_id)
            out.append(Accepted(proposal_id=p.id, action="resolve", appended_atom=new.id))

        elif p.action == "adopt":
            tool_id = getattr(item.payload, "tool_id", None)
            cap = AtomEnvelope(
                id=uuid4(), kind="persona.capability", made_on=_now(), made_by=made_by, made_in=session_id,
                links=[item.id], tier=p.tier, status="live", persona_id=persona_id, tool_id=tool_id,
            )
            store.append(cap)
            _mark_item(store, item, "adopt", cap.id, cycle_id)
            out.append(Accepted(proposal_id=p.id, action="adopt", appended_atom=cap.id))

        elif p.action == "revise":
            new = _identity_from(p, None, "value", session_id, made_by, [item.id], None)
            store.append(new)
            _mark_item(store, item, "revise", new.id, cycle_id)
            out.append(Accepted(proposal_id=p.id, action="revise", appended_atom=new.id))

        elif p.action == "defer":
            new_id = _mark_item(store, item, "defer", None, cycle_id, bump_defer=True)
            out.append(Accepted(proposal_id=p.id, action="defer", appended_atom=new_id))

    return out
