"""Coolant-pump component profile."""

from ntf_insight.components.base import ComponentProfile

COOLANT_PUMP_PROFILE = ComponentProfile(
    profile_id="coolant_pump",
    display_name="Coolant Pump",
    aliases=["coolant pump", "kühlmittelpumpe", "kuehlmittelpumpe"],
    primary_ecus=["CPC3"],
    description=(
        "Initial NTF Insight use case. The pump itself is treated as a low-intelligence "
        "component; vehicle diagnostics and CPC3 monitoring provide the main diagnostic evidence."
    ),
    notes=[
        "DTC-to-root-cause mappings remain intentionally empty until real SMR-D data is parsed.",
        "Thresholds and pre/post windows must be validated on real field cases.",
    ],
)
