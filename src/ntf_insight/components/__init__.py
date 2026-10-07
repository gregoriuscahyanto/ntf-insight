"""Component-specific profiles layered on the generic NTF core."""

from ntf_insight.components.base import ComponentProfile
from ntf_insight.components.registry import get_component_profile, list_component_profiles

__all__ = ["ComponentProfile", "get_component_profile", "list_component_profiles"]
