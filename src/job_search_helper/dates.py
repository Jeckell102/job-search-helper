"""Conservative, readable source dates without inventing missing precision."""
from datetime import date, datetime, timedelta, timezone
import re


DATE_PARSER_VERSION = "source-date-v1"


def normalize_source_date(value: str, *, epoch_milliseconds: bool = False) -> str | None:
    value = value.strip()
    try:
        # Lever documents these fields as milliseconds. Other numeric IDs are
        # deliberately not interpreted as timestamps.
        if epoch_milliseconds and re.fullmatch(r"\d{13}", value):
            stamp = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=int(value))
            return stamp.isoformat().replace("+00:00", "Z")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value).isoformat()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?", value):
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is not None:
                stamp = stamp.astimezone(timezone.utc)
            return stamp.isoformat().replace("+00:00", "Z")
        for pattern in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
            try:
                return datetime.strptime(value, pattern).date().isoformat()
            except ValueError:
                pass
    except (ValueError, OverflowError):
        pass
    return None


def readable_timestamp(value: str | None) -> str:
    return value.replace("T", " ").replace("Z", " UTC") if value else "Unknown"
