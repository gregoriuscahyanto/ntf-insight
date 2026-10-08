"""Audit metadata for manually entered and corrected case information."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ManualAction(StrEnum):
    CREATE_CASE = "create_case"
    ADD_EVENT = "add_event"
    CORRECT_EVENT = "correct_event"


class ManualChange(BaseModel):
    """An immutable before/after audit trail stored next to the case snapshot."""

    model_config = ConfigDict(frozen=True)

    change_id: str = Field(default_factory=lambda: uuid4().hex)
    case_id: str
    action: ManualAction
    entity_type: str
    event_id: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: str = "local_user"
    before_json: str | None = None
    after_json: str
    source_ref: str | None = None
