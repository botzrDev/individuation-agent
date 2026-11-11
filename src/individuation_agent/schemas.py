"""Location of the six JSON Schema contracts.

Resolution order: the repo's top-level ``schemas/`` directory (dev install),
then ``schemas/`` packaged beside this module (wheel install).
"""

from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _resolve() -> Path:
    repo_root = _HERE.parent.parent  # src/individuation_agent -> repo root
    candidate = repo_root / "schemas"
    if candidate.is_dir():
        return candidate
    packaged = _HERE / "schemas"
    if packaged.is_dir():
        return packaged
    raise FileNotFoundError("schemas/ directory not found for individuation_agent")


SCHEMA_DIR: Path = _resolve()
