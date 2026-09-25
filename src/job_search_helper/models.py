"""Policy-free records at the boundary between adapters and local storage."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import TYPE_CHECKING, Any, Mapping
from uuid import uuid4

from .posting import canonicalize_url, material_hash
from .dates import normalize_source_date

if TYPE_CHECKING:
    from .ats import Inventory


MATERIAL_HASH_VERSION = "legacy-v1"
NORMALIZER_VERSION = "adapter-v1"
INVENTORY_PAYLOAD_VERSION = 1
FETCH_STATUSES = frozenset({"complete", "partial", "blocked", "failed", "unsupported"})
COMPANY_STATUSES = ("active", "paused", "archived")
JOB_STATUSES = ("active", "missing", "closed", "unknown")
APPLICATION_STATUSES = ("interested", "preparing", "applied", "interviewing", "offer", "accepted",
                        "rejected", "withdrawn", "archived", "unknown")
OPEN_APPLICATION_STATUSES = ("interested", "preparing", "applied", "interviewing", "offer")


def new_id() -> str:
    return str(uuid4())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceScope:
    source_id: str
    canonical_inventory_url: str
    adapter_version: str
    parameters_json: str = "{}"

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.adapter_version.strip():
            raise ValueError("Source scope requires a source ID and adapter version")
        url = canonicalize_url(self.canonical_inventory_url)
        if not url:
            raise ValueError("Source scope requires an inventory URL")
        parameters = json.loads(self.parameters_json)
        if not isinstance(parameters, dict):
            raise ValueError("Scope parameters must be a JSON object")
        object.__setattr__(self, "canonical_inventory_url", url)
        object.__setattr__(self, "parameters_json", canonical_json(parameters))

    @property
    def fingerprint(self) -> str:
        return fingerprint(asdict(self))


@dataclass(frozen=True)
class JobPosting:
    posting_id: str = ""
    requisition_id: str = ""
    title: str = ""
    location: str = ""
    work_arrangement: str = ""
    compensation: str = ""
    description: str = ""
    department: str = ""
    url: str = ""
    is_listed: bool = True
    source_created_raw: str = ""
    source_modified_raw: str = ""
    metadata_json: str = "{}"

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name != "is_listed" and not isinstance(value, str):
                raise ValueError(f"Posting {name} must be text")
        if type(self.is_listed) is not bool:
            raise ValueError("Posting is_listed must be a boolean")
        if not self.posting_id.strip() and not self.url.strip():
            raise ValueError("Posting requires a public ID or URL")
        if self.url:
            canonicalize_url(self.url)
        metadata = json.loads(self.metadata_json)
        if not isinstance(metadata, dict):
            raise ValueError("Posting metadata must be a JSON object")
        object.__setattr__(self, "metadata_json", canonical_json(metadata))

    @classmethod
    def from_adapter(cls, row: Mapping[str, Any]) -> JobPosting:
        fields = {name: row.get(name, "") for name in (
            "posting_id", "title", "location", "work_arrangement", "compensation",
            "description", "department", "url",
        )}
        fields.update(requisition_id=row.get("req_id", ""), is_listed=row.get("is_listed", True),
                      source_created_raw=row.get("created_at", ""),
                      source_modified_raw=row.get("updated_at", ""))
        known = set(fields) | {"req_id", "created_at", "updated_at"}
        fields["metadata_json"] = canonical_json({key: value for key, value in row.items() if key not in known})
        return cls(**fields)

    @property
    def material_hash(self) -> str:
        return material_hash(asdict(self))

    @property
    def evidence_hash(self) -> str:
        return fingerprint(asdict(self))

    @property
    def source_created_at(self) -> str | None:
        return self._source_date(self.source_created_raw)

    @property
    def source_modified_at(self) -> str | None:
        return self._source_date(self.source_modified_raw)

    def _source_date(self, value: str) -> str | None:
        provider = json.loads(self.metadata_json).get("ats", "")
        return normalize_source_date(value, epoch_milliseconds=str(provider).lower() == "lever")


@dataclass(frozen=True)
class InventorySnapshot:
    scope: SourceScope
    status: str
    jobs: tuple[JobPosting, ...]
    reason: str = ""
    source_url: str = ""
    provider: str = ""

    def __post_init__(self) -> None:
        if self.status not in FETCH_STATUSES:
            raise ValueError(f"Unknown inventory status: {self.status}")
        if not isinstance(self.scope, SourceScope):
            raise ValueError("Inventory requires an explicit source scope")
        object.__setattr__(self, "jobs", tuple(self.jobs))
        if any(not isinstance(job, JobPosting) for job in self.jobs):
            raise ValueError("Inventory jobs must be JobPosting records")

    @classmethod
    def from_adapter(cls, inventory: Inventory, scope: SourceScope) -> InventorySnapshot:
        # Copy every posting, including unlisted and personally excluded titles.
        return cls(scope, inventory.status, tuple(JobPosting.from_adapter(row) for row in inventory.jobs),
                   inventory.reason, inventory.source_url, inventory.ats)
