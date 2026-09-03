"""Configuration for the competition reasoning pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass
class AgentConfig:
    """Stable knobs for the conservative competition runtime.

    The formal default is deliberately one fixed path: three plain candidates,
    one verifier call per candidate, majority selection, and bounded recovery.
    Legacy strategy fields remain accepted so older local callers can construct
    the config, but they no longer enable a second formal solving pipeline.
    """

    formal_candidate_count: ClassVar[int] = 3
    formal_verifier_calls_per_candidate: ClassVar[int] = 1

    # Retained only so older callers can still construct AgentConfig. The
    # formal runtime uses the ClassVar constants above, not these legacy knobs.
    tool_candidates: int = 0
    plain_candidates: int = 3
    verifier_voting_times: int = 1

    policy_temperature: float = 0.6
    verifier_temperature: float = 0.0
    critic_temperature: float = 0.3
    reflection_temperature: float = 0.3

    max_tokens: int = 8192
    verifier_max_tokens: int = 1024
    critic_max_tokens: int = 1024
    fallback_max_tokens: int = 512
    calculation_reasoning_target_tokens: int = 1800
    proof_reasoning_target_tokens: int = 3500
    recovery_max_tokens: int = 2048
    max_recoveries_per_candidate: int = 1
    max_recovery_requests: int = 4

    policy_thinking_mode: bool = False
    verifier_thinking_mode: bool = False
    critic_thinking_mode: bool = False

    enable_tools: bool = False
    enable_critic: bool = False
    enable_reflection: bool = False
    enable_fallback: bool = True
    enable_deterministic_verification: bool = False
    max_tool_rounds: int = 3
    tool_timeout_seconds: float = 5.0
    max_model_requests: int = 6
    max_total_tokens: int = 200_000
    max_tool_calls: int = 48
    problem_timeout_seconds: float = 600.0
    max_problem_chars: int = 20_000
    max_metadata_chars: int = 20_000

    def __post_init__(self) -> None:
        for name in (
            "max_tokens",
            "verifier_max_tokens",
            "critic_max_tokens",
            "fallback_max_tokens",
            "calculation_reasoning_target_tokens",
            "proof_reasoning_target_tokens",
            "recovery_max_tokens",
            "max_model_requests",
            "max_total_tokens",
            "max_tool_calls",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("max_recoveries_per_candidate", "max_recovery_requests"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.max_recoveries_per_candidate > 1:
            raise ValueError("max_recoveries_per_candidate cannot exceed 1")
