"""Persona Register and Archetype Table.

The register answers "which mask is the agent wearing and under what bounds";
the table answers "which archetype does this context call for". Both are
loaded from YAML and are read-only during a cycle; a cycle may append
capability atoms to the store, never edit these files.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .checks import evaluate
from .models import Archetype, Check, CognitiveMode


class Persona(BaseModel):
    id: str
    archetype: Archetype
    display_name: str
    system_prompt_overrides: list[str] = Field(default_factory=list)
    capability_bounds: list[str] = Field(default_factory=list)
    context_filters: list[Check] = Field(default_factory=list)
    cognitive_mode: CognitiveMode
    switch_conditions: list[Check] = Field(default_factory=list)


class PersonaRegister(BaseModel):
    personas: list[Persona]
    active: str

    def resolve(self, archetype: Archetype) -> Persona:
        for p in self.personas:
            if p.archetype == archetype:
                return p
        raise KeyError(archetype)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "PersonaRegister":
        return cls.model_validate(yaml.safe_load(Path(path).read_text("utf-8")))


class ArchetypeEntry(BaseModel):
    archetype: Archetype
    activation_conditions: list[Check] = Field(default_factory=list)
    default_cognitive_mode: CognitiveMode


class ArchetypeTable(BaseModel):
    entries: list[ArchetypeEntry]
    default: Archetype = "Sage"

    def route(self, context_text: str) -> Archetype:
        for entry in self.entries:
            if entry.activation_conditions and all(
                evaluate(c, context_text) == "PASS" for c in entry.activation_conditions
            ):
                return entry.archetype
        return self.default

    @classmethod
    def from_yaml(cls, path: Path | str) -> "ArchetypeTable":
        return cls.model_validate(yaml.safe_load(Path(path).read_text("utf-8")))
