from ntf_insight.domain.reference import DTCTriggerDefinition
from ntf_insight.storage.reference_repositories import InMemoryReferenceRepository


def test_multiple_trigger_definitions_can_exist_for_same_dtc() -> None:
    first = DTCTriggerDefinition(
        definition_id="a", ecu="CPC3", dtc_code="P1", software_scope="SW-A"
    )
    second = DTCTriggerDefinition(
        definition_id="b", ecu="CPC3", dtc_code="P1", software_scope="SW-B"
    )
    repo = InMemoryReferenceRepository([first, second])

    assert len(repo.find_triggers("cpc3", "p1")) == 2
    assert repo.find_trigger("CPC3", "P1") is first
