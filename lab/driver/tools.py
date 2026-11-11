"""Task tools shared by every condition. Twelve tools, the persona's capability bounds. Each call is
reported to the session (so the P-agent's Ego Core records it as an ``ego.tool_call`` atom) and a
scenario-injected fault turns into an ERROR line and an ``ego.error`` atom. The tools are deliberately
small; what matters is that they exist, can be called, can fail, and read the mounted artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from langchain_core.tools import StructuredTool

from lab.workload.generate import TOOLS_IN


@dataclass
class ToolContext:
    mount_root: Path
    faults: dict[str, str] = field(default_factory=dict)  # tool_id -> error signature
    on_call: Callable[[str], None] = lambda tool_id: None
    on_error: Callable[[str], None] = lambda signature: None
    docs_out: Path | None = None


def task_tools(ctx: ToolContext) -> list[StructuredTool]:
    def guard(tool_id: str, fn: Callable[[], str]) -> str:
        ctx.on_call(tool_id)
        sig = ctx.faults.get(tool_id)
        if sig:
            ctx.on_error(sig)
            return f"ERROR: {sig}"
        try:
            return fn()
        except Exception as e:  # a tool crash is reported, never swallowed
            ctx.on_error(f"{tool_id}: {type(e).__name__}")
            return f"ERROR: {tool_id}: {type(e).__name__}: {e}"

    def _path(ref: str) -> Path:
        p = (ctx.mount_root / ref).resolve()
        p.relative_to(ctx.mount_root.resolve())
        return p

    def read_file(ref: str) -> str:
        """Read a mounted file by its relative path."""
        def go() -> str:
            p = _path(ref)
            return p.read_text(encoding="utf-8") if p.is_file() else f"ERROR: no such file: {ref}"
        return guard("read_file", go)

    def grep(pattern: str) -> str:
        """Search the mounted files for a regular expression."""
        def go() -> str:
            rx = re.compile(pattern)
            out = []
            for p in sorted(ctx.mount_root.rglob("*")):
                if p.is_file():
                    for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                        if rx.search(line):
                            out.append(f"{p.relative_to(ctx.mount_root).as_posix()}:{n}: {line}")
            return "\n".join(out) or "(no matches)"
        return guard("grep", go)

    def list_dir(path: str = ".") -> str:
        """List the mounted files under a directory."""
        def go() -> str:
            p = _path(path)
            if not p.is_dir():
                return f"ERROR: no such directory: {path}"
            return "\n".join(sorted(x.relative_to(ctx.mount_root).as_posix() for x in p.rglob("*") if x.is_file())) or "(empty)"
        return guard("list_dir", go)

    def run_check(name: str) -> str:
        """Run a named check and report its verdict."""
        return guard("run_check", lambda: f"check {name}: PASS")

    def write_doc(path: str, content: str) -> str:
        """Write a document to the output area."""
        def go() -> str:
            out = (ctx.docs_out or ctx.mount_root.parent / "docs_out") / path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content, encoding="utf-8")
            return f"wrote {path} ({len(content)} chars)"
        return guard("write_doc", go)

    def query_db(query: str) -> str:
        """Query the database for migration or schema information."""
        return guard("query_db", lambda: "rows: 3 (schema_migrations: 0042_add_index, 0043_backfill, 0044_drop_legacy)")

    def diff_check(ref: str) -> str:
        """Report structural changes in a mounted file."""
        return guard("diff_check", lambda: f"{ref}: no structural changes" if _path(ref).is_file() else f"ERROR: no such file: {ref}")

    def render_table(rows: str) -> str:
        """Render lines of text as a Markdown table."""
        return guard("render_table", lambda: "| " + " |\n| ".join(r.strip() for r in rows.splitlines() if r.strip()) + " |")

    def spell_check(text: str) -> str:
        """Spell-check a piece of text."""
        return guard("spell_check", lambda: f"spell check: 0 issues in {len(text.split())} words")

    def link_check(text: str) -> str:
        """Check the links in a piece of text."""
        return guard("link_check", lambda: f"link check: {len(re.findall(r'https?://', text))} links, 0 broken")

    def lint_md(text: str) -> str:
        """Lint a piece of Markdown."""
        return guard("lint_md", lambda: "lint: clean")

    def build_docs(target: str = "site") -> str:
        """Build the documentation site."""
        return guard("build_docs", lambda: f"build {target}: ok")

    fns = [read_file, grep, run_check, write_doc, query_db, diff_check, list_dir, render_table, spell_check, link_check,
           lint_md, build_docs]
    assert {f.__name__ for f in fns} == set(TOOLS_IN)
    return [StructuredTool.from_function(f, name=f.__name__, description=f.__doc__) for f in fns]
