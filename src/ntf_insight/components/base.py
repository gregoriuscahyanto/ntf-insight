"""Component profile definitions.

Profiles contain component-specific engineering context without leaking it into the generic
case, storage or UI layers.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ComponentProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    primary_ecus: list[str] = Field(default_factory=list)
    description: str = ""
    notes: list[str] = Field(default_factory=list)
