"""The ``about`` convention: one stable key per subject, so two claims about the same thing can be
compared. The live model is told the convention in its system prompt; the scripted model applies it
by regex. Both arrive at the same key for the same wording, which is what the contradiction detector
needs."""

from __future__ import annotations

import re

_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bthe canonical (\w+) is\b"), "decision:{0}"),
    (re.compile(r"\b(max_retries)\b"), "decision:{0}"),
    (re.compile(r"\bruling on ([^:]+):"), "decision:policy:{0}"),
    (re.compile(r"\byou owe (the [\w\- ]+?) the (.+?) by\b"), "commitment:{0}:{1}"),
    (re.compile(r"\byour rule: (\S+ \S+ \S+ \S+)"), "preference:{0}"),
    (re.compile(r"\bthe tool (\w+) is\b"), "identity:tool:{0}"),
    (re.compile(r"\bthe ([\w\-]+) module is documented\b"), "identity:module:{0}"),
    (re.compile(r"\bdocumenting the ([\w\-]+) module\b"), "identity:module:{0}"),
    (re.compile(r"^(the .+?) lives at\b"), "identity:path:{0}"),
    (re.compile(r"\bnext deploy is\b"), "identity:deploy-safety"),
]


def subject_key(text: str) -> str:
    t = text.strip()
    for pattern, template in _RULES:
        m = pattern.search(t)
        if m:
            return template.format(*[g.strip().lower().replace(" ", "-") for g in m.groups()])
    words = re.findall(r"[\w'-]+", t.lower())
    return "identity:" + "-".join(words[:4])
