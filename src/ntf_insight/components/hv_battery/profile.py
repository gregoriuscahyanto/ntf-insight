"""HV-battery component profile placeholder."""

from ntf_insight.components.base import ComponentProfile

HV_BATTERY_PROFILE = ComponentProfile(
    profile_id="hv_battery",
    display_name="HV Battery",
    aliases=["hv battery", "battery", "hochvoltbatterie"],
    primary_ecus=[],
    description="Future component profile demonstrating that the core is not pump-specific.",
)
