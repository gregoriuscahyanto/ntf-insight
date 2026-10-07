from ntf_insight.app.bootstrap import load_application_data
from ntf_insight.app.settings import AppPaths
from ntf_insight.demo.synthetic_cases import build_demo_cases
from ntf_insight.storage.duckdb_store import DuckDBStore


def _paths(tmp_path) -> AppPaths:
    data_dir = tmp_path / "data"
    return AppPaths(
        data_dir=data_dir,
        raw_dir=data_dir / "raw",
        database_path=data_dir / "ntf.duckdb",
    )


def test_bootstrap_uses_demo_when_database_has_no_cases(tmp_path) -> None:
    data = load_application_data(_paths(tmp_path))

    assert data.mode == "demo"
    assert data.cases.list_cases()


def test_bootstrap_uses_local_cases_when_database_is_populated(tmp_path) -> None:
    paths = _paths(tmp_path)
    paths.ensure()
    store = DuckDBStore(paths.database_path)
    store.save_case(build_demo_cases()[0])

    data = load_application_data(paths)

    assert data.mode == "local"
    assert [case.case_id for case in data.cases.list_cases()] == ["DEMO-001"]
