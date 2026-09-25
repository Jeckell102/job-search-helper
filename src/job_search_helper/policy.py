"""Explicit, neutral-by-default local screening profiles."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import tomllib
import unicodedata

from .config import _keys, workspace_path
from .models import canonical_json, fingerprint


POLICY_VERSION = "local-policy-v1"
ARRANGEMENTS = {"remote", "hybrid", "onsite"}


@dataclass(frozen=True)
class Policy:
    document: str

    @property
    def rules(self) -> dict:
        return json.loads(self.document)

    @property
    def fingerprint(self) -> str:
        return fingerprint({"format_version": POLICY_VERSION, "rules": self.rules})

    @property
    def enabled(self) -> bool:
        rules = self.rules
        return bool(rules["titles"]["exclude"] or rules["titles"]["prefer"]
                    or rules["locations"]["work_arrangements"] or rules["salary"])


def _phrases(value, field):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be a list of nonempty phrases")
    if len(value) > 200 or any(len(item) > 200 for item in value):
        raise ValueError(f"{field} allows up to 200 phrases of at most 200 characters")
    result = []
    for item in value:
        if item.strip().casefold().startswith("regex:"):
            raise ValueError(f"{field} supports literal phrases, not regex entries")
        words = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", item).casefold())
        if not words:
            raise ValueError(f"{field} requires phrases containing words")
        result.append(" ".join(words))
    return sorted(set(result))


def parse_policy(data: dict) -> Policy:
    _keys(data, {"schema_version", "titles", "salary", "locations"}, "profile")
    if type(data.get("schema_version", 1)) is not int or data.get("schema_version", 1) != 1:
        raise ValueError("profile.schema_version must be 1")
    titles, salary, locations = (data.get(key, {}) for key in ("titles", "salary", "locations"))
    _keys(titles, {"exclude", "prefer"}, "titles")
    _keys(salary, {"minimum", "currency", "period"}, "salary")
    _keys(locations, {"work_arrangements"}, "locations")
    if salary:
        if set(salary) != {"minimum", "currency", "period"}:
            raise ValueError("salary requires minimum, currency and period together")
        minimum = salary["minimum"]
        if type(minimum) not in (int, float) or not 0 < minimum <= 1_000_000_000 or not math.isfinite(minimum):
            raise ValueError("salary.minimum must be a finite positive amount up to 1000000000")
        if salary["currency"] != "USD" or salary["period"] != "annual":
            raise ValueError("This evaluator supports only salary.currency='USD' and salary.period='annual'")
        salary = dict(salary, minimum=float(minimum))
    arrangements = locations.get("work_arrangements", [])
    if not isinstance(arrangements, list) or any(not isinstance(item, str) or item not in ARRANGEMENTS for item in arrangements):
        raise ValueError("locations.work_arrangements must list remote, hybrid or onsite")
    return Policy(canonical_json({
        "titles": {key: _phrases(titles.get(key, []), "titles." + key) for key in ("exclude", "prefer")},
        "salary": salary, "locations": {"work_arrangements": sorted(set(arrangements))},
    }))


def load_policy(workspace: Path, path: str | Path | None = None) -> Policy:
    """No explicit file means neutral rules, regardless of legacy files or env."""
    if path is None:
        return parse_policy({})
    source = workspace_path(workspace, path)
    try:
        with source.open("rb") as handle:
            data = handle.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError("Profile exceeds 1 MiB")
        return parse_policy(tomllib.loads(data.decode("utf-8-sig")))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read profile {source}: {exc}") from exc
