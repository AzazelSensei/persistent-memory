"""`.pm-council.yaml` loading and validation for the AI Council.

Reads the project-level council configuration (backends, roles, round
count, prompt override) and validates it into a `CouncilConfig`. Any
malformed input — broken YAML, non-UTF-8 or oversized file, non-string
YAML keys, unknown backend, duplicate member ids, out-of-range limits,
unsupported version — surfaces as `CouncilConfigError` so callers never
see a raw YAML, TypeError, RecursionError, or pydantic exception.

Member `id`, `model`, and `effort` end up on a subprocess argv (Phase 3),
so they are restricted to an argv-safe character set. `members` and the
round count are capped so a config cannot silently authorize an
unbounded number of paid headless CLI calls.
"""

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from persistent_memory.council.models import MAX_PROMPT_CHARS, MAX_ROLE_CHARS

MAX_MEMBER_ROLE_CHARS = 600

CONFIG_FILENAME = ".pm-council.yaml"
SUPPORTED_CONFIG_VERSION = 1
DEFAULT_ROUNDS = 2
MAX_ROUNDS = 5
DEFAULT_TURN_TIMEOUT_SECONDS = 600
MAX_TURN_TIMEOUT_SECONDS = 3600
COUNCIL_BACKENDS = ("claude", "codex", "kimi", "grok")
DEFAULT_MEMBER_IDS = ("claude", "codex", "grok")

MAX_MEMBERS = 6
MAX_TOTAL_TURN_CALLS = 24
MAX_CONFIG_BYTES = 262144

MEMBER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
ARGV_SAFE_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_MODEL_CHARS = 64
MAX_EFFORT_CHARS = 16


class CouncilConfigError(ValueError):
    pass


def _validate_argv_safe_field(value: str, field_name: str, max_chars: int) -> str:
    if len(value) > max_chars:
        raise ValueError(f"{field_name} must be at most {max_chars} characters")
    if value.startswith("-"):
        raise ValueError(f"{field_name} must not start with '-'")
    if not ARGV_SAFE_PATTERN.match(value):
        raise ValueError(f"{field_name} may only contain letters, digits, '.', '_', '-'")
    return value


class CouncilMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    backend: str
    role: str | None = Field(default=None, max_length=MAX_MEMBER_ROLE_CHARS)
    model: str | None = None
    effort: str | None = None
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, value: str) -> str:
        if not MEMBER_ID_PATTERN.match(value):
            raise ValueError(f"member id {value!r} must match pattern {MEMBER_ID_PATTERN.pattern}")
        return value

    @field_validator("model")
    @classmethod
    def validate_model_argv_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_argv_safe_field(value, "model", MAX_MODEL_CHARS)

    @field_validator("effort")
    @classmethod
    def validate_effort_argv_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_argv_safe_field(value, "effort", MAX_EFFORT_CHARS)

    @model_validator(mode="after")
    def validate_backend_known(self) -> "CouncilMember":
        if self.backend not in COUNCIL_BACKENDS:
            raise ValueError(f"unknown backend {self.backend!r}, must be one of {COUNCIL_BACKENDS}")
        return self


class CouncilConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    spokesperson: str | None = None
    rounds: int = Field(default=DEFAULT_ROUNDS, ge=1, le=MAX_ROUNDS)
    turn_timeout_seconds: int = Field(
        default=DEFAULT_TURN_TIMEOUT_SECONDS, ge=1, le=MAX_TURN_TIMEOUT_SECONDS
    )
    members: list[CouncilMember] = Field(min_length=1, max_length=MAX_MEMBERS)
    prompt: str | None = Field(default=None, max_length=MAX_PROMPT_CHARS)
    replace_global_prompt: bool = False

    @model_validator(mode="after")
    def validate_version_supported(self) -> "CouncilConfig":
        if self.version != SUPPORTED_CONFIG_VERSION:
            raise ValueError(
                f"config version {self.version} is not supported "
                f"(this build supports version {SUPPORTED_CONFIG_VERSION})"
            )
        return self

    @model_validator(mode="after")
    def validate_member_ids_unique(self) -> "CouncilConfig":
        ids = [member.id for member in self.members]
        if len(ids) != len(set(ids)):
            raise ValueError(f"member ids must be unique, got {ids}")
        return self

    @model_validator(mode="after")
    def validate_spokesperson_is_enabled_member(self) -> "CouncilConfig":
        if self.spokesperson is None:
            return self
        members_by_id = {member.id: member for member in self.members}
        spokesperson = members_by_id.get(self.spokesperson)
        if spokesperson is None:
            raise ValueError(f"spokesperson {self.spokesperson!r} is not a member")
        if not spokesperson.enabled:
            raise ValueError(f"spokesperson {self.spokesperson!r} must be enabled")
        return self

    @model_validator(mode="after")
    def validate_total_turn_calls_within_cap(self) -> "CouncilConfig":
        enabled_count = sum(1 for member in self.members if member.enabled)
        total_calls = enabled_count * self.rounds + 1
        if total_calls > MAX_TOTAL_TURN_CALLS:
            raise ValueError(
                f"{enabled_count} enabled members x {self.rounds} rounds + 1 synthesis "
                f"= {total_calls} calls, exceeds the cap of {MAX_TOTAL_TURN_CALLS}"
            )
        return self


def council_config_path(project_root: Path) -> Path:
    return Path(project_root) / CONFIG_FILENAME


def default_council_config() -> CouncilConfig:
    members = [CouncilMember(id=member_id, backend=member_id) for member_id in DEFAULT_MEMBER_IDS]
    return CouncilConfig(
        version=SUPPORTED_CONFIG_VERSION,
        spokesperson=DEFAULT_MEMBER_IDS[0],
        rounds=DEFAULT_ROUNDS,
        turn_timeout_seconds=DEFAULT_TURN_TIMEOUT_SECONDS,
        members=members,
    )


def format_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", ()))
        msg = error.get("msg", "")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts)


def load_council_config(project_root: Path) -> tuple[CouncilConfig, str]:
    path = council_config_path(project_root)
    if not path.exists():
        return default_council_config(), "default"

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise CouncilConfigError(f"cannot read {path}: {exc}") from exc

    if len(raw_bytes) > MAX_CONFIG_BYTES:
        raise CouncilConfigError(f"{path} exceeds the {MAX_CONFIG_BYTES} byte config size limit")

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CouncilConfigError(f"{path} is not valid UTF-8: {exc}") from exc

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CouncilConfigError(f"invalid YAML in {path}: {exc}") from exc
    except RecursionError as exc:
        raise CouncilConfigError(f"{path} is too deeply nested to parse") from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise CouncilConfigError(f"{path} must contain a YAML mapping with string keys")

    try:
        config = CouncilConfig(**raw)
    except ValidationError as exc:
        raise CouncilConfigError(format_validation_error(exc)) from exc
    except TypeError as exc:
        raise CouncilConfigError(f"{path} has an invalid structure: {exc}") from exc
    except RecursionError as exc:
        raise CouncilConfigError(f"{path} is too deeply nested to parse") from exc

    return config, "file"
