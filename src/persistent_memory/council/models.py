"""Board message schema for the AI Council: shared, append-only messages.

Defines the BoardMessage pydantic model plus the fixed vocabularies for
message kind and delivery channel (`via`).
"""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

BOARD_MESSAGE_KINDS = ("note", "proposal", "critique", "vote", "decision", "handoff", "question")
BOARD_MESSAGE_VIA = ("mcp", "http", "stdout", "human")

MESSAGE_ID_PATTERN = re.compile(r"^m-\d{4,}$")

MAX_BODY_CHARS = 32000
MAX_REFS = 32
MAX_REF_CHARS = 64
MAX_PROJECT_CHARS = 120
MAX_THREAD_CHARS = 64
MAX_AUTHOR_CHARS = 64
MAX_ROLE_CHARS = 120
MAX_PROMPT_CHARS = 20000


class BoardMessage(BaseModel):
    """A single append-only message on a project's council board."""

    model_config = ConfigDict(extra="forbid")

    id: str
    ts: str
    project: str = Field(max_length=MAX_PROJECT_CHARS)
    thread: str = Field(max_length=MAX_THREAD_CHARS)
    author: str = Field(max_length=MAX_AUTHOR_CHARS)
    kind: str
    body: str = Field(max_length=MAX_BODY_CHARS)
    via: str
    role: str | None = Field(default=None, max_length=MAX_ROLE_CHARS)
    turn: int | None = Field(default=None, ge=0)
    refs: list[str] = Field(default_factory=list, max_length=MAX_REFS)

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, value: str) -> str:
        if not MESSAGE_ID_PATTERN.match(value):
            raise ValueError("id must match the format m-NNNN")
        return value

    @field_validator("project")
    @classmethod
    def validate_project_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("project must not be empty")
        return value

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if value not in BOARD_MESSAGE_KINDS:
            raise ValueError(f"kind must be one of {BOARD_MESSAGE_KINDS}")
        return value

    @field_validator("via")
    @classmethod
    def validate_via(cls, value: str) -> str:
        if value not in BOARD_MESSAGE_VIA:
            raise ValueError(f"via must be one of {BOARD_MESSAGE_VIA}")
        return value

    @field_validator("body")
    @classmethod
    def validate_body_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body must not be empty")
        return value

    @field_validator("refs")
    @classmethod
    def validate_ref_lengths(cls, value: list[str]) -> list[str]:
        for ref in value:
            if len(ref) > MAX_REF_CHARS:
                raise ValueError(f"each ref must be at most {MAX_REF_CHARS} characters")
        return value
