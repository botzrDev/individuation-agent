"""A scripted base model for the lab's plumbing runs (phase A, zero spend).

It is not an agent and proves nothing about the hypothesis. It exists so that every tool, every fault
seed and every stage of the cycle fires deterministically end to end. Three prompt shapes:

- a session turn: parse the user's items, store each with the condition's append tool (reading and
  verifying against the artifact when the turn says to), call the task tool the turn names, then reply;
- a Stage 3 synthesis prompt: resolve contradictions keeping the newer statement, adopt unused tools,
  revise blind spots into a commitment, each rationale citing the probe id;
- an exam probe: search memory with the question and answer with the best hit, or say it cannot recall.
"""

from __future__ import annotations

import json
import re
from typing import Any, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from lab.driver.subjects import subject_key

_ITEM = re.compile(r"\(\d+\)\s*")
_VERIFY = re.compile(r"^open (\S+) and verify that (.+?); record it as verified$")
_LINE = re.compile(r"^([0-9a-f-]{36}): (\w+): (.*)$", re.MULTILINE)
_SIDE_B = re.compile(r"b='(.*)'$")
_APPENDED = re.compile(r"appended ([0-9a-f-]{36})")
_STOP = {"that", "with", "used", "record", "verified", "canonical", "open", "and", "the", "your", "you", "write", "lives"}


def _excerpt_for(statement: str, content: str) -> str | None:
    toks = {w for w in re.findall(r"[\w_]+", statement.lower()) if len(w) >= 4 and w not in _STOP}
    for line in content.splitlines():
        lt = {w for w in re.findall(r"[\w_]+", line.lower()) if len(w) >= 4}
        if toks & lt:
            return line.strip()
    return None


def parse_items(prompt: str) -> list[dict]:
    """The '(1) ...; (2) ...' items of a record turn, with verify items marked."""
    if "For the record: " not in prompt:
        return []
    body = prompt.split("For the record: ", 1)[1]
    body = body.rsplit(". Please record this.", 1)[0]
    items = []
    for raw in _ITEM.split(body):
        raw = raw.strip().rstrip(";").strip()
        if not raw:
            continue
        m = _VERIFY.match(raw)
        if m:
            items.append({"kind": "verify", "ref": m.group(1), "text": m.group(2)})
        else:
            items.append({"kind": "plain", "text": raw})
    return items


class LabScriptedModel(BaseChatModel):
    tool_names: list[str] = []
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "lab-scripted"

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        names = [getattr(t, "name", None) or getattr(t, "__name__", str(t)) for t in tools]
        return LabScriptedModel(tool_names=names)

    # ------------------------------------------------------------------ dispatch

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, run_manager: Any = None,
                  **kwargs) -> ChatResult:
        self.calls += 1
        human_idx = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
        prompt = str(messages[human_idx].content)
        after = messages[human_idx + 1:]
        if "complementary reasoning mode" in prompt:
            return self._reply(self._synthesis(prompt))
        if prompt.startswith("[exam]"):
            return self._exam(prompt, after)
        return self._turn(prompt, after)

    @staticmethod
    def _reply(text: str, tool_calls: list[dict] | None = None) -> ChatResult:
        msg = AIMessage(content=text, tool_calls=tool_calls or [])
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _tc(self, name: str, args: dict, n: int) -> dict:
        return {"name": name, "args": args, "id": f"call_{self.calls}_{n}", "type": "tool_call"}

    # ------------------------------------------------------------------ session turns

    def _turn(self, prompt: str, after: list[BaseMessage]) -> ChatResult:
        p_mode = "memory_append" in self.tool_names
        step = sum(1 for m in after if isinstance(m, AIMessage))
        tool_msgs = [m for m in after if isinstance(m, ToolMessage)]
        items = parse_items(prompt)
        verify_items = [it for it in items if it["kind"] == "verify"]
        calls: list[dict] = []
        n = 0

        def append_call(text: str, about: str | None = None, kind: str = "fact", conf: float = 0.6, **extra) -> dict:
            nonlocal n
            n += 1
            if p_mode:
                return self._tc("memory_append", {"about": about or subject_key(text), "statement": text,
                                                  "atom_kind": kind, "confidence": conf, **extra}, n)
            return self._tc("notes_append", {"text": text + (f" (verified against {extra['artifact_ref']})" if extra.get("artifact_ref") else "")}, n)

        if step == 0:
            if "I believe max_retries is 2" in prompt:
                calls.append(append_call("max_retries is 2 (unverified, from an old note)", "decision:max_retries", conf=0.4))
            if "Run query_db" in prompt:
                n += 1
                calls.append(self._tc("query_db", {"query": "recent schema migrations"}, n))
            if "next deploy is" in prompt:
                calls.append(append_call("the next deploy is guaranteed safe", "identity:deploy-safety", kind="value", conf=0.9))
            for it in verify_items:
                n += 1
                calls.append(self._tc("read_file", {"ref": it["ref"]}, n))
            for it in items:
                if it["kind"] == "plain":
                    kind = "commitment" if it["text"].startswith("you owe") else ("preference" if it["text"].startswith("your rule") else "fact")
                    calls.append(append_call(it["text"], kind=kind))
            if calls:
                return self._reply("", calls)
            return self._reply(self._final(prompt))

        if step == 1 and verify_items:
            # the read results arrived: store each verify item with its artifact ref and the line it rests on
            reads = {}
            for tm in tool_msgs:
                reads[tm.tool_call_id] = str(tm.content)
            contents = [str(tm.content) for tm in tool_msgs if not str(tm.content).startswith(("appended", "noted", "rows:", "ERROR"))]
            for i, it in enumerate(verify_items):
                content = contents[i] if i < len(contents) else ""
                excerpt = _excerpt_for(it["text"], content)
                calls.append(append_call(it["text"], artifact_ref=it["ref"], artifact_excerpt=excerpt))
            return self._reply("", calls)

        if step == 2 and verify_items and p_mode:
            ids = [m.group(1) for tm in tool_msgs for m in [_APPENDED.search(str(tm.content))] if m]
            # the last len(verify_items) appends are the verify items
            for aid in ids[-len(verify_items):]:
                n += 1
                calls.append(self._tc("memory_verify", {"atom_id": aid}, n))
            return self._reply("", calls)

        return self._reply(self._final(prompt))

    @staticmethod
    def _final(prompt: str) -> str:
        if "rollback script" in prompt:
            return "No, the repository has no rollback script. Recorded the migration query result."
        if "Summarize this build log" in prompt:
            return "All six build jobs finished within about a minute each. Recorded the items."
        return "Recorded."

    # ------------------------------------------------------------------ Stage 3

    @staticmethod
    def _synthesis(prompt: str) -> str:
        proposals = []
        for probe_id, cls, rest in _LINE.findall(prompt):
            if cls == "contradiction":
                m = _SIDE_B.search(rest)
                statement = m.group(1) if m else "the newer statement stands"
                proposals.append({"action": "resolve", "target": probe_id,
                                  "rationale": f"resolving {probe_id}: the newer statement in the record stands",
                                  "new_atom": {"statement": statement, "atom_kind": "fact", "confidence": 0.7}})
            elif cls == "unused_capability":
                proposals.append({"action": "adopt", "target": probe_id, "rationale": f"{probe_id}: bound and never called"})
            elif cls == "blind_spot":
                proposals.append({"action": "revise", "target": probe_id,
                                  "rationale": f"{probe_id}: the same error recurred across sessions",
                                  "new_atom": {"statement": "I check the connection pool before I query the database",
                                               "atom_kind": "commitment", "confidence": 0.6}})
        return json.dumps(proposals)

    # ------------------------------------------------------------------ exam

    def _exam(self, prompt: str, after: list[BaseMessage]) -> ChatResult:
        search = "memory_search" if "memory_search" in self.tool_names else "notes_search"
        step = sum(1 for m in after if isinstance(m, AIMessage))
        if step == 0:
            question = prompt.split("]", 1)[1].strip()
            return self._reply("", [self._tc(search, {"query": question}, 1)])
        hits = [str(m.content) for m in after if isinstance(m, ToolMessage)]
        text = hits[0] if hits else ""
        if not text or text.startswith("(no matching"):
            return self._reply("I cannot recall that.")
        first = text.splitlines()[0]
        answer = first.split(" | ")[-1] if " | " in first else first.split("] ", 1)[-1]
        return self._reply(answer)
