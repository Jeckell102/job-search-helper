"""Explicit task modes and conservative handling of no-write instructions.

Objectives never grant coordinator permissions. Recognized prohibitions can only
reduce permissions; this intentionally rejects some narrowly scoped prohibitions
instead of trying to infer which mutations natural language might allow.
"""
import re


_MUTATION = r'(?:edit|change|write|modify|create|add|replace|delete|remove|update|implement|fix|build)'
_PROHIBITIONS = (
    r'\bread[\s-]*only\b',
    r'\b(?:review\s+only|only\s+review|just\s+review)\b',
    r"\b(?:do\s+not|don't|must\s+not|mustn't|should\s+not|shouldn't|shall\s+not|never|cannot|can't)\s+(?:(?:ever|actually|directly)\s+)?" + _MUTATION + r'\b',
    r"\b(?:do\s+not|don't|must\s+not|mustn't|should\s+not|shouldn't|never)\s+make\s+(?:any\s+)?changes?\b",
    r'\bwithout\s+(?:editing|changing|writing|modifying|creating|adding|replacing|deleting|removing|updating|making\s+(?:any\s+)?changes?)\b',
    r'\bno\s+(?:file\s+|code\s+|development\s+)?(?:edits?|changes?|modifications?|writes?)\b',
    r'\b(?:leave|keep)\s+(?:all\s+|the\s+|any\s+)?(?:files?|code|sources?|checkout)\s+(?:unchanged|unmodified|untouched|as\s+is)\b',
)


def prohibits_writes(objective):
    """Return True for supported prohibitions; never infer positive consent."""
    if not isinstance(objective, str):
        raise ValueError('The objective must be text.')
    normalized = objective.casefold().replace('\u2019', "'").replace('\u2018', "'")
    return any(re.search(pattern, normalized) for pattern in _PROHIBITIONS)


def resolve_mode(data):
    """Validate a structured mode, default review, and reject contradictions."""
    if not isinstance(data, dict):
        raise ValueError('A task request must be an object.')
    mode = data.get('mode', 'review')
    if not isinstance(mode, str) or mode not in ('review', 'develop'):
        raise ValueError('Mode must be exactly review or develop.')
    objective = data.get('objective', '')
    if not isinstance(objective, str):
        raise ValueError('The objective must be text.')
    if mode == 'develop' and prohibits_writes(objective):
        raise ValueError('Development mode conflicts with a no-write instruction. Use review mode or remove the conflicting instruction explicitly.')
    return mode
