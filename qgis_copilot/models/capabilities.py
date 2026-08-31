"""Explicit, non-secret model capability profiles for request construction and UI."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BehaviorMode(str, Enum):
    """User-visible behavior choices; never a claim about hidden reasoning."""

    SERVICE_DEFAULT = "service_default"
    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"


@dataclass(frozen=True)
class ModelCapabilityProfile:
    """A verified request contract, not a vendor-marketing label."""

    profile_id: str
    display_name: str
    interface_type: str
    behavior_modes: tuple[BehaviorMode, ...] = (BehaviorMode.SERVICE_DEFAULT,)
    behavior_request_field: str | None = None
    behavior_request_values: tuple[tuple[BehaviorMode, str], ...] = ()

    def supports(self, mode: BehaviorMode) -> bool:
        return mode in self.behavior_modes

    def request_value_for(self, mode: BehaviorMode) -> tuple[str, str] | None:
        if mode == BehaviorMode.SERVICE_DEFAULT or not self.behavior_request_field:
            return None
        for supported_mode, value in self.behavior_request_values:
            if supported_mode == mode:
                return self.behavior_request_field, value
        return None


STANDARD_OPENAI_COMPATIBLE = ModelCapabilityProfile(
    profile_id="standard_openai_compatible",
    display_name="标准 OpenAI-compatible",
    interface_type="OpenAI-compatible /chat/completions",
)

# This profile is intentionally opt-in. It is only suitable for services whose
# documented request contract accepts `reasoning_effort`; it never exposes chain
# of thought and is not sent by the standard profile.
REASONING_EFFORT_COMPATIBLE = ModelCapabilityProfile(
    profile_id="reasoning_effort_compatible",
    display_name="支持 reasoning_effort 的兼容服务",
    interface_type="OpenAI-compatible /chat/completions",
    behavior_modes=(BehaviorMode.SERVICE_DEFAULT, BehaviorMode.FAST, BehaviorMode.BALANCED, BehaviorMode.DEEP),
    behavior_request_field="reasoning_effort",
    behavior_request_values=(
        (BehaviorMode.FAST, "low"),
        (BehaviorMode.BALANCED, "medium"),
        (BehaviorMode.DEEP, "high"),
    ),
)

_PROFILES = {
    STANDARD_OPENAI_COMPATIBLE.profile_id: STANDARD_OPENAI_COMPATIBLE,
    REASONING_EFFORT_COMPATIBLE.profile_id: REASONING_EFFORT_COMPATIBLE,
}


def get_profile(profile_id: str | None) -> ModelCapabilityProfile:
    """Resolve untrusted persisted text safely to the conservative standard profile."""
    return _PROFILES.get((profile_id or "").strip(), STANDARD_OPENAI_COMPATIBLE)


def all_profiles() -> tuple[ModelCapabilityProfile, ...]:
    return tuple(_PROFILES.values())


def behavior_mode_label(mode: BehaviorMode) -> str:
    return {
        BehaviorMode.SERVICE_DEFAULT: "服务默认",
        BehaviorMode.FAST: "快速",
        BehaviorMode.BALANCED: "平衡",
        BehaviorMode.DEEP: "深度",
    }[mode]
