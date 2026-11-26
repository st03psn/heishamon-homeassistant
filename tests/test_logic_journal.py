"""Test the journal of setting changes."""
from custom_components.aquarea.logic.journal import Change, SettingsJournal


def journal():
    return SettingsJournal({"Quiet_Mode_Level", "Z1_Heat_Request_Temp"})


def test_first_value_is_the_baseline():
    j = journal()
    assert j.update(0, "Quiet_Mode_Level", "0") is None
    assert j.update(10, "Quiet_Mode_Level", "0") is None
    assert j.entries == []


def test_change_without_a_command_comes_from_elsewhere():
    j = journal()
    j.update(0, "Quiet_Mode_Level", "0")
    change = j.update(100, "Quiet_Mode_Level", "2")
    assert change == Change(100, "Quiet_Mode_Level", "0", "2", "other")
    assert j.entries == [change]


def test_change_after_a_command_was_asked_for():
    j = journal()
    j.update(0, "Z1_Heat_Request_Temp", "0")
    j.note_command(100, "Z1_Heat_Request_Temp")
    assert j.update(108, "Z1_Heat_Request_Temp", "1").origin == "home_assistant"
    # a later change without a new command is not
    assert j.update(500, "Z1_Heat_Request_Temp", "0").origin == "other"
    # a command for another setting does not count
    j.note_command(600, "Quiet_Mode_Level")
    assert j.update(605, "Z1_Heat_Request_Temp", "2").origin == "other"


def test_other_topics_are_ignored():
    j = journal()
    assert j.update(0, "Main_Outlet_Temp", "30") is None
    assert j.update(5, "Main_Outlet_Temp", "31") is None
    assert "Main_Outlet_Temp" not in j.values


def test_only_the_newest_entries_are_kept():
    j = SettingsJournal({"Quiet_Mode_Level"}, max_entries=3)
    j.update(0, "Quiet_Mode_Level", "0")
    for i in range(1, 6):
        j.update(i, "Quiet_Mode_Level", str(i))
    assert [e.new for e in j.entries] == ["3", "4", "5"]


def test_store_and_restore():
    j = journal()
    j.update(0, "Quiet_Mode_Level", "0")
    j.update(1, "Quiet_Mode_Level", "1")
    restored = SettingsJournal({"Quiet_Mode_Level"})
    restored.restore(j.as_dict())
    assert restored.entries == j.entries
    # the stored value is the baseline: the same value again records nothing
    assert restored.update(50, "Quiet_Mode_Level", "1") is None
    # a change while Home Assistant was not running is recorded when it is seen
    assert restored.update(60, "Quiet_Mode_Level", "3").old == "1"
