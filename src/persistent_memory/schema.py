"""Schema for memory records: typed frontmatter model plus (de)serialization.

Defines the Record/Provenance pydantic models, the record type and status
enums, and the parse/serialize functions for the on-disk markdown format
(YAML frontmatter between `---` delimiters, followed by a markdown body).
"""

import datetime
import re
from enum import Enum

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RecordType(str, Enum):
    DECISION = "decision"
    LESSON = "lesson"
    PRINCIPLE = "principle"


class RecordStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    REVERTED_AS_MISTAKE = "reverted-as-mistake"


class Provenance(BaseModel):
    """Where a record came from: capture session, working directory, agent."""

    model_config = ConfigDict(extra="forbid")

    session: str
    cwd: str
    agent: str


ID_PATTERN = re.compile(r"^(D|L|P)-\d{4}$")
TYPE_TO_PREFIX = {
    RecordType.DECISION: "D",
    RecordType.LESSON: "L",
    RecordType.PRINCIPLE: "P",
}
SALIENCE_MIN = 0.0
SALIENCE_MAX = 1.0


class Record(BaseModel):
    """Frontmatter of a single memory record.

    The id prefix (D/L/P) must match the record type, and the
    `superseded-by` frontmatter key maps to the `superseded_by` field.
    """

    model_config = ConfigDict(populate_by_name=True, use_enum_values=False)

    id: str
    type: RecordType
    status: RecordStatus
    date: datetime.date
    project: str
    provenance: Provenance
    tags: list[str] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)
    superseded_by: list[str] = Field(default_factory=list, alias="superseded-by")
    salience: float = Field(ge=SALIENCE_MIN, le=SALIENCE_MAX)

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, value: str) -> str:
        if not ID_PATTERN.match(value):
            raise ValueError("id must match the format <D|L|P>-NNNN")
        return value

    @model_validator(mode="after")
    def validate_id_prefix_matches_type(self) -> "Record":
        expected = TYPE_TO_PREFIX[self.type]
        if self.id.split("-", 1)[0] != expected:
            raise ValueError("id prefix does not match record type")
        return self


FRONTMATTER_DELIMITER = "---"
FRONTMATTER_FIELD_ORDER = [
    "id",
    "type",
    "status",
    "date",
    "project",
    "provenance",
    "tags",
    "supersedes",
    "superseded-by",
    "salience",
]


def parse_document(text: str) -> tuple[Record, str]:
    """Parse a record document into (validated frontmatter, markdown body).

    Raises ValueError (or pydantic ValidationError, a ValueError subclass)
    when the frontmatter is missing, malformed, or fails schema validation.
    """
    if not text.startswith(FRONTMATTER_DELIMITER):
        raise ValueError("frontmatter not found: document does not start with ---")
    parts = text.split(FRONTMATTER_DELIMITER, 2)
    if len(parts) < 3:
        raise ValueError("closing frontmatter delimiter (---) not found")
    raw = yaml.safe_load(parts[1])
    if not isinstance(raw, dict):
        raise ValueError("frontmatter is not a valid YAML mapping")
    record = Record.model_validate(raw)
    body = parts[2].lstrip("\n")
    return record, body


def serialize_document(record: Record, body: str) -> str:
    """Render a record back to markdown with frontmatter keys in stable order."""
    dumped = record.model_dump(by_alias=True, mode="json")
    ordered = {key: dumped[key] for key in FRONTMATTER_FIELD_ORDER if key in dumped}
    front = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"{FRONTMATTER_DELIMITER}\n{front}{FRONTMATTER_DELIMITER}\n{body.rstrip()}\n"
