"""Registry of installed component profiles."""

from __future__ import annotations

from ntf_insight.components.base import ComponentProfile
from ntf_insight.components.coolant_pump.profile import COOLANT_PUMP_PROFILE
from ntf_insight.components.hv_battery.profile import HV_BATTERY_PROFILE

DCDC_CONVERTER_PROFILE = ComponentProfile(
    profile_id="dcdc_converter",
    display_name="DC/DC-Wandler",
    aliases=["DC/DC-Wandler", "DC DC Converter", "Gleichspannungswandler"],
    # Keine erfundenen DTC-/ECU-Zuordnungen: konfigurierbar je Sachnummer.
)
OTHER_COMPONENT_PROFILE = ComponentProfile(
    profile_id="other_component",
    display_name="Weiteres Bauteil",
    description="Offenes QEC-Profil mit projektbezogener Sachnummer und ECU-Liste.",
)

_PROFILES = {
    COOLANT_PUMP_PROFILE.profile_id: COOLANT_PUMP_PROFILE,
    HV_BATTERY_PROFILE.profile_id: HV_BATTERY_PROFILE,
    DCDC_CONVERTER_PROFILE.profile_id: DCDC_CONVERTER_PROFILE,
    OTHER_COMPONENT_PROFILE.profile_id: OTHER_COMPONENT_PROFILE,
}


def list_component_profiles() -> list[ComponentProfile]:
    return list(_PROFILES.values())


def get_component_profile(profile_id: str) -> ComponentProfile:
    try:
        return _PROFILES[profile_id]
    except KeyError as exc:
        raise KeyError(f"Unknown component profile: {profile_id}") from exc
