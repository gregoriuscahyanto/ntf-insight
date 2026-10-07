from ntf_insight.demo.synthetic_cases import build_demo_repository


def test_demo_repository_contains_unique_cases() -> None:
    repository = build_demo_repository()
    cases = repository.list_cases()

    assert len(cases) == 6
    assert len({case.case_id for case in cases}) == len(cases)
    assert all(case.vin.startswith("DEMO-") for case in cases)
