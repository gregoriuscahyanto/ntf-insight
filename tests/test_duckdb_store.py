from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.demo.synthetic_reference import build_demo_reference_repository
from ntf_insight.storage.duckdb_store import DuckDBStore


def test_duckdb_roundtrip_for_cases_and_reference_data(tmp_path) -> None:
    store = DuckDBStore(tmp_path / "ntf.duckdb")
    cases = build_demo_cases()
    references = build_demo_reference_repository()

    store.save_cases(cases)
    store.save_reference_data(references.list_triggers(), references.list_changes())

    loaded_cases = store.load_cases()
    loaded_triggers = store.load_triggers()
    loaded_changes = store.load_changes()

    assert [case.case_id for case in loaded_cases] == [case.case_id for case in cases]
    assert len(loaded_triggers) == len(references.list_triggers())
    assert len(loaded_changes) == len(references.list_changes())
