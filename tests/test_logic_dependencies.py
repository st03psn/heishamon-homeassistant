"""Test which settings have no effect with the current values."""
from custom_components.aquarea.logic.dependencies import (
    Reason,
    blocked_commands,
    inactive_topics,
    rules_apply_to,
)
from custom_components.aquarea.logic.dependency_data import REQUIREMENTS


def test_unknown_parent_blocks_nothing():
    assert blocked_commands({}) == {}
    assert inactive_topics({}) == {}


def test_child_of_a_parent_that_is_off():
    values = {"Pump_Flowrate_Mode": "1"}
    blocked = blocked_commands(values)
    assert blocked["SetFloorHeatDelta"] == [
        Reason("TOP106", "Pump_Flowrate_Mode", ("0",), "1")
    ]
    assert "SetFloorCoolDelta" in blocked
    assert set(inactive_topics(values)) == {"TOP23", "TOP24"}
    assert blocked_commands({"Pump_Flowrate_Mode": "0"}) == {}


def test_parent_with_several_good_values():
    assert "SetSolarOnDelta" in blocked_commands({"Solar_Mode": "0"})
    assert "SetSolarOnDelta" not in blocked_commands({"Solar_Mode": "1"})
    assert "SetSolarOnDelta" not in blocked_commands({"Solar_Mode": "2"})


def test_chain_of_parents():
    # bivalent off: its settings are blocked; the advanced parallel settings
    # are judged by their own parent only
    values = {"Bivalent_Control": "0", "Bivalent_Mode": "0", "Bivalent_Advanced_Heat": "0"}
    blocked = blocked_commands(values)
    assert [r.parent_topic for r in blocked["SetBivalentStartTemp"]] == ["TOP129"]
    assert [r.parent_topic for r in blocked["SetBivalentAPHeat"]] == ["TOP130"]
    assert [r.parent_topic for r in blocked["SetBivalentAPStartTemp"]] == ["TOP132"]


def test_two_parents_of_one_setting():
    blocked = blocked_commands({"Bivalent_Control": "0", "Bivalent_Operating_Mode": "1"})
    assert [r.parent_topic for r in blocked["SetBivalentMode"]] == ["TOP129", "TOP180"]


def test_commands_shared_with_other_settings_are_never_blocked():
    values = {
        "Cooling_Enable": "0",
        "External_Heat_Cool_Control": "1",
        "Zone_Configuration": "0",
        "SG_Ready_Control": "0",
    }
    blocked = blocked_commands(values)
    assert not {"SetOperationMode", "SetCurves", "SetMainSchedule"} & set(blocked)
    assert all(" " not in command for command in blocked)
    # the plain children of the same rules are blocked
    assert "SetCoolingWaterMode" in blocked and "SetZ2HeatRequestTemperature" in blocked


def test_optional_pcb_does_not_block_the_bivalent_operating_mode():
    blocked = blocked_commands({"Optional_PCB": "0"})
    assert "SetSolarMode" in blocked
    assert "SetBivalentOperatingMode" not in blocked


def test_rules_that_cannot_be_judged_are_skipped():
    # the rule on the bivalent external pump has an alternative without a value
    assert "SetBivalentExternalPump" not in blocked_commands({"Bivalent_Mode": "2"})


def test_data_is_consistent():
    assert len(REQUIREMENTS) == 21
    assert sum(1 for r in REQUIREMENTS if r.blocks) == 1
    for requirement in REQUIREMENTS:
        for condition in requirement.when + requirement.any_of:
            assert condition.topic.startswith("TOP") and condition.values


def test_extra_pump_use_does_not_need_a_dhw_tank():
    blocked = blocked_commands({"DHW_Installed": "0"})
    assert "SetDHWHeatDelta" in blocked and "SetExtraPumpMode" in blocked
    assert "SetExtraPump" not in blocked
    assert "TOP182" not in inactive_topics({"DHW_Installed": "0"})


def test_rules_apply_to_the_m_series_only():
    assert rules_apply_to("WH-SDC0316M9E8 9 3ph T-CAP - M-series")
    assert rules_apply_to("WH-ADC0316M9E8AN2 12 3ph T-CAP - M-series DHW 185l")
    assert rules_apply_to("WH-WXG09ME8 9 3ph")
    assert not rules_apply_to("WH-MDC05H3E5 5 1ph HP")
    assert not rules_apply_to("WH-MXC09J3E8 9 3ph T-CAP")
    assert not rules_apply_to("WH-SDC0509L3E5 9 1 ph HP - split L-series 3kW elec heating")
    assert not rules_apply_to("WH-ADC0309K3E5 9 1ph HP - K-series All-in-One R32")
    assert not rules_apply_to(None) and not rules_apply_to("")
