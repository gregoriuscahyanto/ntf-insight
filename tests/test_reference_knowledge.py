from ntf_insight.domain.reference import ChangeKind, DTCTriggerDefinition, ECUChangeRecord


def test_dtc_trigger_definition_normalizes_fault_key() -> None:
    definition = DTCTriggerDefinition(
        definition_id="trigger-1",
        ecu=" cpc3 ",
        dtc_code=" p26f100 ",
        trigger_text="Synthetic trigger condition",
    )

    assert definition.fault_key == ("CPC3", "P26F100")


def test_ecu_change_record_can_link_affected_dtc() -> None:
    change = ECUChangeRecord(
        change_id="change-1",
        ecu="CPC3",
        kind=ChangeKind.SOFTWARE,
        from_version="1.0",
        to_version="1.1",
        affected_dtcs=["P26F100"],
        change_summary="Synthetic diagnostic logic change",
    )

    assert change.kind == ChangeKind.SOFTWARE
    assert "P26F100" in change.affected_dtcs
