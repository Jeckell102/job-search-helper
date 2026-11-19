"""Token-accurate text-chat budgeting for the installed Qwen3.5 4B family.

Qwen's pinned official Hugging Face tokenizer and Jinja chat template exactly
matched all 24 recorded Ollama prompt token counts in the 2026-11-08 baseline.

Only the executable runtime assets live on ai-computer. The asset installer
verifies their SHA256s, and the model weights stay in Ollama unchanged.

Ollama's num_predict includes both private reasoning and final answer tokens:
a remaining generation allowance is *not* a guaranteed final-answer quota.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path

CHAT_TEMPLATE_SHA256 = "316230d6a809701f4db5ea8f8fc862bc3a6f3229c937c174e674ff3ca0a64ac8"
TOKENIZER_SHA256 = "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42"
TOKENIZER_FAMILY = "Qwen/Qwen3.5-4B"
TOKENIZER_REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"

# Guard against future template drift or a backend that adds prompt fields.
SAFETY_MARGIN_TOKENS = 32
MINIMUM_GENERATION_TOKENS = 64
MAX_MESSAGES = 24
MAX_TEXT_BYTES = 64 * 1024
SUPPORTED_ROLES = frozenset({"system", "user", "assistant"})
_RESOURCE_DIR = Path(__file__).resolve().parent / "resources" / "qwen35"


@dataclass(frozen=True)
class ContextEstimate:
    context_tokens: int
    prompt_tokens: int
    message_count: int
    safety_margin_tokens: int
    available_generation_tokens: int
    thinking_enabled: bool
    method: str = "qwen35_official_tokenizer_template_v1"


def _verified_file(path: Path, expected_sha: str) -> bytes:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"Qwen tokenizer runtime asset missing: {path.name}") from exc
    if hashlib.sha256(payload).hexdigest() != expected_sha:
        raise RuntimeError(f"Qwen tokenizer runtime asset checksum mismatch: {path.name}")
    return payload


@lru_cache(maxsize=1)
def _runtime():
    """Load the immutable tokenizer once on MuleLab, outside the scraper venv."""
    import sys
    vendor = str(Path(__file__).with_name('coordinator_vendor'))
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    from tokenizers import Tokenizer
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    _verified_file(_RESOURCE_DIR / "tokenizer.json", TOKENIZER_SHA256)
    config = json.loads(
        _verified_file(_RESOURCE_DIR / "tokenizer_config.json", CHAT_TEMPLATE_SHA256)
    )
    chat_template = config.get("chat_template")
    if not isinstance(chat_template, str) or not chat_template:
        raise RuntimeError("Pinned Qwen tokenizer configuration has no chat template.")

    environment = ImmutableSandboxedEnvironment(
        extensions=["jinja2.ext.loopcontrols", "jinja2.ext.do"]
    )

    def reject(message):
        raise ValueError(str(message))

    template = environment.from_string(chat_template)
    tokenizer = Tokenizer.from_file(str(_RESOURCE_DIR / "tokenizer.json"))
    return tokenizer, template, reject


def estimate_context(messages: list[dict], context_tokens: int, *, thinking: bool = False, tools=None, internal_tools=False) -> ContextEstimate:
    """Count the full serialized Qwen text-chat prompt, including role/control tokens.

    The supported route is text-only; unsupported message structures are rejected
    before serialization. Nothing is silently removed or summarized.
    """
    if type(context_tokens) is not int or context_tokens < 512:
        raise ValueError("Invalid effective model context limit.")
    if type(thinking) is not bool:
        raise ValueError("Thinking mode must be boolean.")
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise ValueError(f"Provide between 1 and {MAX_MESSAGES} messages.")

    text_bytes = 0
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") not in (SUPPORTED_ROLES | {'tool'} if internal_tools else SUPPORTED_ROLES)
            or not isinstance(message.get("content"), str)
        ):
            raise ValueError("Text system, user, or assistant message content is required.")
        text_bytes += len(message["content"].encode("utf-8"))
        if internal_tools:
            text_bytes += len(json.dumps(message.get('tool_calls',[])).encode())
        if text_bytes > MAX_TEXT_BYTES:
            raise ValueError("Text request exceeds the bounded tokenizer input size.")

    tokenizer, template, reject = _runtime()
    rendered = template.render(
        messages=messages,
        tools=tools,
        add_generation_prompt=True,
        enable_thinking=thinking,
        raise_exception=reject,
    )
    prompt_tokens = len(tokenizer.encode(rendered, add_special_tokens=False).ids)
    available = max(0, context_tokens - prompt_tokens - SAFETY_MARGIN_TOKENS)
    return ContextEstimate(
        context_tokens=context_tokens,
        prompt_tokens=prompt_tokens,
        message_count=len(messages),
        safety_margin_tokens=SAFETY_MARGIN_TOKENS,
        available_generation_tokens=available,
        thinking_enabled=thinking,
    )


def require_output_room(estimate: ContextEstimate, requested_tokens: int) -> None:
    """Fail closed if a requested generation cannot fit; do not truncate input."""
    if type(requested_tokens) is not int or requested_tokens < 1:
        raise ValueError("Output limit must be a positive integer.")
    if estimate.available_generation_tokens < requested_tokens:
        raise ValueError(
            "Input plus requested output exceeds the token-calibrated context budget."
        )


def ensure_generation_room(estimate: ContextEstimate) -> None:
    """Do not send a request that cannot return a minimally useful answer."""
    if estimate.available_generation_tokens < MINIMUM_GENERATION_TOKENS:
        raise ValueError("Not enough model context remains for a useful answer.")
