from ntf_insight.components.registry import get_component_profile, list_component_profiles


def test_coolant_pump_profile_is_registered() -> None:
    profile = get_component_profile("coolant_pump")

    assert profile.display_name == "Coolant Pump"
    assert "CPC3" in profile.primary_ecus
    assert len(list_component_profiles()) >= 2
