from ntf_insight.analysis.supplier_metrics import build_supplier_summaries
from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.domain.population import PopulationExposure


def test_supplier_rate_is_blank_without_population_denominator() -> None:
    summaries = build_supplier_summaries(build_demo_cases())

    assert summaries
    assert all(item.ntf_per_1000_installed is None for item in summaries)


def test_supplier_ntf_rate_uses_installed_population() -> None:
    exposures = [
        PopulationExposure(
            exposure_id="exp-a",
            component_type="Coolant Pump",
            supplier="Supplier A",
            installed_units=2000,
        )
    ]
    summaries = build_supplier_summaries(build_demo_cases(), exposures)
    supplier_a = next(item for item in summaries if item.supplier == "Supplier A")

    assert supplier_a.installed_units == 2000
    assert supplier_a.ntf_per_1000_installed == supplier_a.return_ntf_count / 2000 * 1000
