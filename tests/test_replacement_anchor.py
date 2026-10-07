from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.domain.events import PartReplacement


def test_explicit_replacement_anchor_wins_over_earliest_fallback() -> None:
    case = build_demo_cases()[0].model_copy(deep=True)
    later = PartReplacement(
        vin=case.vin,
        occurred_at=case.replacements[0].occurred_at.replace(day=20),
        mileage_km=25000,
        component_type=case.component_type,
        supplier="Supplier Z",
    )
    case.replacements.append(later)
    case.investigated_replacement_id = later.event_id

    assert case.investigated_replacement() is not None
    assert case.investigated_replacement().event_id == later.event_id
