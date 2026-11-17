"""Explicit model profiles; all output limits use Qwen's measured context budget."""
from dataclasses import dataclass

from context_budget import (
    ensure_generation_room,
    estimate_context,
    require_output_room,
)

CONTRACT_VERSION = "c15-token-accurate-1.0"

VISIBLE_PROFILES = {
    "Instant": "qwen-instant:4b",
    "Wrapper Coder": "qwen-wrapper:4b",
    "Advanced": "qwen-advanced:4b",
    "Pro": "qwen-pro:4b",
}

LEGACY_ALIASES = {
    "mule-orchestrator": "qwen-instant:4b",
    "jetson-assistant": "qwen-instant:4b",
}


@dataclass(frozen=True)
class Profile:
    model_id: str
    think: bool
    max_output_tokens: int
    context_tokens: int
    temperature: float
    top_p: float
    top_k: int
    presence_penalty: float
    generation_timeout_seconds: int


PROFILES = {
    "qwen-instant:4b": Profile("qwen-instant:4b", False, 512, 4096, 0.7, 0.8, 20, 1.5, 120),
    "qwen-advanced:4b": Profile("qwen-advanced:4b", True, 1536, 4096, 1.0, 0.95, 20, 1.5, 240),
    "qwen-pro:4b": Profile("qwen-pro:4b", True, 4096, 4096, 1.0, 0.95, 20, 1.5, 420),
    "qwen-wrapper:4b": Profile("qwen-wrapper:4b", False, 3072, 12288, 0.2, 0.9, 20, 0.0, 240),
}


def resolve_profile(model_id):
    if model_id is None:
        model_id = "Instant"
    name = VISIBLE_PROFILES.get(model_id, LEGACY_ALIASES.get(model_id, model_id))
    if name not in PROFILES:
        raise ValueError("Unknown local AI profile.")
    return PROFILES[name]


def resolve_output_limit(messages, profile, requested=None, *, thinking_override=None, tools=None):
    """Reserve exact prompt tokens, then cap output within the remaining context.

    Reasoning and final-answer tokens share this allowance in Ollama; no promise
    is made that a thinking model will leave enough to emit a final answer.
    """
    if thinking_override is not None and type(thinking_override) is not bool:
        raise ValueError("Thinking override must be boolean.")
    thinking = profile.think if thinking_override is None else thinking_override
    estimate = estimate_context(messages, profile.context_tokens, thinking=thinking, tools=tools)
    ensure_generation_room(estimate)
    if requested is None:
        return min(profile.max_output_tokens, estimate.available_generation_tokens)
    if type(requested) is not int or not 1 <= requested <= profile.max_output_tokens:
        raise ValueError("Requested output exceeds this profile ceiling.")
    require_output_room(estimate, requested)
    return requested
