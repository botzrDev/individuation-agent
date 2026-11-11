"""Append-only JSONL atom store.

One JSON object per line. The newest line for an ``id`` is the current view
of that atom. No method rewrites or deletes a line; ``supersede`` appends,
``consult`` appends. The file only grows.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from .models import MODEL_BY_KIND, AtomEnvelope, AtomStatus, to_row, validate_row


class AtomStore:
    def __init__(self, path: Path, validate: bool = False):
        """``validate=True`` (lab mode) checks every row against the envelope schema before it is written,
        which is what enforces the cross-referenced property: no links means ``terminal`` must be true."""
        self.path = Path(path)
        self.validate = validate
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    # ------------------------------------------------------------------ write

    def append(self, atom: AtomEnvelope) -> UUID:
        row = to_row(atom)
        if self.validate:
            validate_row(row, "atom-envelope.schema.json")
        line = json.dumps(row, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return atom.id

    def supersede(self, old_id: UUID, new: AtomEnvelope) -> UUID:
        old = self.get(old_id)
        new = new.model_copy(update={"supersedes": old_id})
        self.append(new)
        self.append(old.model_copy(update={"status": "superseded"}))
        return new.id

    def mark_superseded(self, old_id: UUID) -> None:
        """Append a superseded copy of ``old_id`` without appending a replacement (the caller already did)."""
        old = self.get(old_id)
        self.append(old.model_copy(update={"status": "superseded"}))

    def consult(self, id: UUID, session_id: str) -> None:
        target = self.get(id)
        self.append(
            AtomEnvelope(
                id=uuid4(),
                kind="ego.consult",
                made_on=datetime.now(timezone.utc),
                made_by=session_id,
                made_in=session_id,
                about=str(id),
                links=[id],
                tier="VERIFIED",
                status="live",
                by_author=(session_id == target.made_in),
            )
        )

    # ------------------------------------------------------------------- read

    def _rows(self) -> list[dict]:
        rows = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    def _current(self) -> dict[str, dict]:
        """Newest row per id, in first-seen order."""
        current: dict[str, dict] = {}
        for row in self._rows():
            current[row["id"]] = row
        return current

    def _hydrate(self, row: dict) -> AtomEnvelope:
        model = MODEL_BY_KIND.get(row["kind"], AtomEnvelope)
        return model.model_validate(row)

    def _last_read_for(self, id: UUID) -> datetime | None:
        latest: datetime | None = None
        for row in self._rows():
            if row["kind"] == "ego.consult" and row.get("about") == str(id) and not row.get("by_author", False):
                latest = datetime.fromisoformat(row["made_on"])
        return latest

    def get(self, id: UUID) -> AtomEnvelope:
        row = self._current().get(str(id))
        if row is None:
            raise KeyError(id)
        atom = self._hydrate(row)
        if atom.kind != "ego.consult":
            last = self._last_read_for(id)
            if last is not None:
                atom = atom.model_copy(update={"last_read": last})
        return atom

    def all(self, kind: str | None = None, status: AtomStatus | None = None) -> list[AtomEnvelope]:
        out = []
        for row in self._current().values():
            if row["kind"] == "ego.consult":
                continue
            if kind is not None and row["kind"] != kind:
                continue
            if status is not None and row["status"] != status:
                continue
            out.append(self._hydrate(row))
        return out

    def latest(self, kind: str) -> AtomEnvelope | None:
        live = self.all(kind=kind, status="live")
        return live[-1] if live else None

    def line_count(self) -> int:
        return len(self._rows())
