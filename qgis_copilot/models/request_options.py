"""Build provider request options from a verified capability profile."""
from __future__ import annotations

from .capabilities import BehaviorMode, ModelCapabilityProfile


def build_request_options(profile: ModelCapabilityProfile, mode: BehaviorMode) -> dict:
    """Return only fields declared by the selected profile."""
    if not profile.supports(mode):
        raise ValueError(f"模型能力档案不支持行为模式：{mode.value}")
    option = profile.request_value_for(mode)
    return {option[0]: option[1]} if option else {}
