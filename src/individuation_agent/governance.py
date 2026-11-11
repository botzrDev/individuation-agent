"""The acceptance filter inside Stage 4.

Governance is not a wrapper around the cycle; it is the gate that decides
which self-reorganization proposals the agent is allowed to apply. Three
verdicts, each PASS | FAIL | UNKNOWN. A crash is UNKNOWN, never PASS.
"""

from __future__ import annotations

from uuid import UUID

from .checks import evaluate
from .models import ConstraintAtom, Governance as GovernanceVerdicts, ObligationAtom, Proposal, Rejected, ShadowItem, Verdict
from .reconcile import Ledger, reconcile
from .store import AtomStore

MAX_DEFER = 3
_ATOM_KINDS = {"fact", "value", "commitment", "preference", "capability"}


def new_atom_is_valid(p: Proposal) -> bool:
    """resolve and revise must carry a usable identity claim; the rationale is never written as a fact."""
    if p.action not in ("resolve", "revise"):
        return True
    a = p.new_atom
    if not isinstance(a, dict):
        return False
    statement = a.get("statement")
    if not isinstance(statement, str) or not statement.strip():
        return False
    if "atom_kind" in a and a["atom_kind"] not in _ATOM_KINDS:
        return False
    if "confidence" in a:
        c = a["confidence"]
        if isinstance(c, bool) or not isinstance(c, (int, float)) or not 0.0 <= float(c) <= 1.0:
            return False
    return True


class Governance:
    def __init__(self, store: AtomStore, ledger: Ledger | None = None, session_id: str = "governance"):
        self.store = store
        self.ledger = ledger
        self.session_id = session_id

    # ---------------------------------------------------------------- checks

    def _constraint_check(self, proposals: list[Proposal]) -> tuple[Verdict, dict[UUID, str]]:
        """Per-proposal FAILs keyed by proposal id, plus the overall verdict."""
        blocked: dict[UUID, str] = {}
        saw_unknown = False
        try:
            for c in self.store.all(kind="archetype.constraint", status="live"):
                if not isinstance(c, ConstraintAtom):
                    continue
                if c.check is None:
                    saw_unknown = True
                    continue
                for p in proposals:
                    if p.id in blocked:
                        continue
                    v = evaluate(c.check, p.rationale, store=self.store)
                    if v == "FAIL":
                        blocked[p.id] = c.name
                    elif v == "UNKNOWN":
                        saw_unknown = True
        except Exception:
            return "UNKNOWN", blocked
        if blocked:
            return "FAIL", blocked
        return ("UNKNOWN" if saw_unknown else "PASS"), blocked

    def _obligation_check(self) -> tuple[Verdict, str | None]:
        try:
            for o in self.store.all(kind="ego.obligation", status="live"):
                if isinstance(o, ObligationAtom) and o.obligation_status == "BREACHED":
                    return "FAIL", o.name
        except Exception:
            return "UNKNOWN", None
        return "PASS", None

    def _reconcile(self) -> Verdict:
        """With a ledger wired, reconcile the two stores now; PASS when nothing is left unresolved.
        With a single store there is nothing to reconcile and the verdict is PASS (documented).
        With the total precedence relation in reconcile.py the verdict is PASS or UNKNOWN (the
        reconcile itself raised); FAIL is reserved for a partial relation that leaves conflicts undecided."""
        if self.ledger is None:
            return "PASS"
        try:
            report = reconcile(self.store, self.ledger, self.session_id)
        except Exception:
            return "UNKNOWN"
        return "FAIL" if report.unresolved else "PASS"

    # ---------------------------------------------------------------- filter

    def filter(
        self, proposals: list[Proposal], items_by_id: dict[UUID, ShadowItem]
    ) -> tuple[list[Proposal], list[Rejected], GovernanceVerdicts]:
        r_verdict = self._reconcile()  # first: obligation state may arrive through the ledger
        c_verdict, blocked = self._constraint_check(proposals)
        o_verdict, breached = self._obligation_check()

        accepted: list[Proposal] = []
        rejected: list[Rejected] = []
        for p in proposals:
            if o_verdict == "FAIL":
                rejected.append(Rejected(proposal_id=p.id, blocked_by=f"obligation:{breached}"))
            elif p.id in blocked:
                rejected.append(Rejected(proposal_id=p.id, blocked_by=blocked[p.id]))
            elif p.action == "defer" and p.target in items_by_id and items_by_id[p.target].defer_count >= MAX_DEFER:
                rejected.append(Rejected(proposal_id=p.id, blocked_by="max_defer"))
            elif not new_atom_is_valid(p):
                rejected.append(Rejected(proposal_id=p.id, blocked_by="new_atom_invalid"))
            else:
                accepted.append(p)

        return accepted, rejected, GovernanceVerdicts(
            constraint_check=c_verdict, obligation_check=o_verdict, reconcile=r_verdict
        )
