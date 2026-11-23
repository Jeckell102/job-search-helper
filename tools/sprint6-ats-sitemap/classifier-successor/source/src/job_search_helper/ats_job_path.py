"""Isolated model edit for ATS Corporation job paths."""
import re
from collections.abc import Callable

classify_job_path: Callable[[str], str] | None = None
