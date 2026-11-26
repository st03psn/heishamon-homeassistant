"""Settings dependencies of the Panasonic Aquarea / HeishaMon, transcribed from MQTT-Topics.md
(section "Settings that depend on other settings", ref origin/settings-dependencies)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Condition:
    """A topic having one of the given raw values (as HeishaMon publishes them)."""

    topic: str  # "TOP110"
    name: str  # topic name below main/, e.g. "Optional_PCB"
    values: tuple[str, ...]  # raw payloads, e.g. ("1",) or ("22", "38")


@dataclass(frozen=True)
class Requirement:
    """Table A: the children are only shown or adjustable while ALL `when` conditions hold
    (use `any_of` instead when the table says 'or')."""

    when: tuple[Condition, ...] = ()
    any_of: tuple[Condition, ...] = ()
    child_topics: tuple[str, ...] = ()  # "TOP146", ...
    child_commands: tuple[str, ...] = ()  # "SetZoneType", ... exactly as written
    source: str = ""  # the Source column verbatim
    note: str = ""  # anything in the row not expressible above, verbatim


@dataclass(frozen=True)
class Effect:
    """Table B: the setting is adjustable but only takes effect under a condition."""

    topics: tuple[str, ...]
    when: tuple[Condition, ...] = ()
    text: str = ""  # the 'Takes effect only when' cell verbatim (also when it is a range rule, not a condition)
    source: str = ""


@dataclass(frozen=True)
class Coupling:
    """Table C: changing a setting changes something else or raises a fault."""

    topics: tuple[str, ...]
    text: str  # the Effect cell verbatim
    fault: str | None = None  # e.g. "H43" when the row names a fault code
    tested_on_unit: bool = False  # True when the cell says '(test unit)'


SOURCE_NOTE: str = ('HeishaMon does not check settings against each other: a command is sent as it is, also when the '
 'setting it belongs to is switched off. The heat pump itself accepts such values (tested on M '
 'series only; may work on other series, not tested there). The remote controller and the Aquarea '
 'Service Cloud hide or grey out these fields. An integration that wants to behave like them can '
 'use the tables below.\n'
 '\n'
 'Sources: service manual of WH-SDC0316M9E8 / WH-WXG09ME8 ("SM" and page), the operating manual of '
 'the M series ("BA" and page), and the Aquarea Service Cloud on the M-series test unit ("Cloud": '
 'greyed out while the parent was off). Evidence for the Cloud and the test unit: '
 '[AquareaParity.md](AquareaParity.md), sections 3.4 and 3.5. Other series may differ.')


REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement(
        when=(Condition('TOP110', 'Optional_PCB', ('1',)),),
        any_of=(),
        child_topics=('TOP146', 'TOP101', 'TOP121', 'TOP150', 'TOP149', 'TOP122', 'TOP120', 'TOP180'),
        child_commands=('SetZoneType', 'SetSolarMode', 'SetExternalError', 'SetDemandControlEnable', 'SetSGReadyMode', 'SetExternalCompressorControl', 'SetExternalHeatCoolControl', 'SetBivalentOperatingMode'),
        source='SM 97, 100-106; Cloud',
        note='child TOP180 is listed as "bivalent operating mode SG ready (TOP180 = 1)"',
    ),
    Requirement(
        when=(Condition('TOP100', 'DHW_Installed', ('1',)),),
        any_of=(),
        child_topics=('TOP140', 'TOP148', 'TOP151', 'TOP182', 'TOP183', 'TOP158', 'TOP159', 'TOP22', 'TOP70', 'TOP71', 'TOP58', 'TOP9'),
        child_commands=('SetSmartDHW', 'SetDHWHeaterType', 'SetDHWDefrost', 'SetExtraPump', 'SetExtraPumpMode', 'SetRoomOperationMaxTime', 'SetDHWHeatupMaxTime', 'SetDHWHeatDelta', 'SetSterilizationTemp', 'SetSterilizationMaxTime', 'SetDHWHeaterState', 'SetDHWTemp', 'SetForceDHW'),
        source='SM 97-98, 100-101; BA 19, 28, 33, 48; Cloud',
        note='DHW operation modes (no topic given)',
    ),
    Requirement(
        when=(Condition('TOP148', 'DHW_Heater_Type', ('1',)),),
        any_of=(),
        child_topics=('TOP173',),
        child_commands=('SetDHWBoosterDelay',),
        source='SM 101; BA 33',
        note='',
    ),
    Requirement(
        when=(Condition('TOP99', 'Buffer_Installed', ('1',)),),
        any_of=(),
        child_topics=('TOP113',),
        child_commands=('SetBufferDelta',),
        source='SM 101; BA 33',
        note='',
    ),
    Requirement(
        when=(Condition('TOP129', 'Bivalent_Control', ('1',)),),
        any_of=(),
        child_topics=('TOP180', 'TOP131', 'TOP130'),
        child_commands=('SetBivalentOperatingMode', 'SetBivalentStartTemp', 'SetBivalentMode'),
        source='SM 102; BA 34; Cloud',
        note='',
    ),
    Requirement(
        when=(Condition('TOP180', 'Bivalent_Operating_Mode', ('0',)),),
        any_of=(),
        child_topics=('TOP130',),
        child_commands=('SetBivalentMode',),
        source='SM 102; BA 34',
        note='',
    ),
    Requirement(
        when=(Condition('TOP130', 'Bivalent_Mode', ('2',)),),
        any_of=(),
        child_topics=('TOP132', 'TOP133'),
        child_commands=('SetBivalentAPHeat', 'SetBivalentAPDHW'),
        source='SM 102; BA 34',
        note='',
    ),
    Requirement(
        when=(Condition('TOP132', 'Bivalent_Advanced_Heat', ('1',)),),
        any_of=(),
        child_topics=('TOP134', 'TOP135', 'TOP136', 'TOP137'),
        child_commands=('SetBivalentAPStartTemp', 'SetBivalentAPStopTemp', 'SetBivalentAPStartDelay', 'SetBivalentAPStopDelay'),
        source='BA 34-35; Cloud',
        note='',
    ),
    Requirement(
        when=(Condition('TOP133', 'Bivalent_Advanced_DHW', ('1',)),),
        any_of=(),
        child_topics=('TOP138',),
        child_commands=(),
        source='BA 35',
        note='no command ("–")',
    ),
    Requirement(
        when=(),
        any_of=(Condition('TOP130', 'Bivalent_Mode', ('0',)),),
        child_topics=('TOP181',),
        child_commands=('SetBivalentExternalPump',),
        source='BA 34-35; Cloud',
        note='parent: Bivalent mode alternative (TOP130 = 0), or operating mode SG ready / intelligent; children: Bivalent external pump (TOP181); or operating mode SG ready / intelligent (no value given)',
    ),
    Requirement(
        when=(Condition('TOP101', 'Solar_Mode', ('1', '2')),),
        any_of=(),
        child_topics=('TOP102', 'TOP103', 'TOP104', 'TOP105'),
        child_commands=('SetSolarOnDelta', 'SetSolarOffDelta', 'SetSolarFrostProtection', 'SetSolarHighLimit'),
        source='SM 103; BA 38; Cloud',
        note='',
    ),
    Requirement(
        when=(Condition('TOP149', 'SG_Ready_Control', ('1',)),),
        any_of=(),
        child_topics=('TOP154', 'TOP155', 'TOP156', 'TOP157', 'TOP191', 'TOP192'),
        child_commands=('SetSGReadyHeatCapacity1', 'SetSGReadyDHWCapacity1', 'SetSGReadyCoolCapacity1', 'SetSGReadyHeatCapacity2', 'SetSGReadyDHWCapacity2', 'SetSGReadyCoolCapacity2'),
        source='SM 105, 190; BA 39; Cloud',
        note='',
    ),
    Requirement(
        when=(Condition('TOP149', 'SG_Ready_Control', ('2',)),),
        any_of=(),
        child_topics=('TOP184', 'TOP185', 'TOP186', 'TOP187', 'TOP188', 'TOP189', 'TOP190'),
        child_commands=('SetSGReadyHeatPower1 ... SetSGReadyStopPower',),
        source='SM 105, 190; BA 39; Cloud',
        note='command range not expanded',
    ),
    Requirement(
        when=(Condition('TOP139', 'Heating_Control', ('1',)),),
        any_of=(),
        child_topics=('TOP174', 'TOP175', 'TOP176'),
        child_commands=('SetEfficiencyStage1Time', 'SetEfficiencyStage2Time', 'SetEfficiencyStage3Time'),
        source='SM 107; BA 41',
        note='',
    ),
    Requirement(
        when=(Condition('TOP106', 'Pump_Flowrate_Mode', ('0',)),),
        any_of=(),
        child_topics=('TOP23', 'TOP24'),
        child_commands=('SetFloorHeatDelta', 'SetFloorCoolDelta'),
        source='SM 107; BA 46-47',
        note='',
    ),
    Requirement(
        when=(),
        any_of=(),
        child_topics=(),
        child_commands=('SetCurves', 'SetZ1HeatRequestTemperature ... SetZ2CoolRequestTemperature'),
        source='SM 109-110; BA 45, 47; Cloud',
        note='parent: Water temperature mode compensation curve / direct (TOP76, TOP81); children: Curve points, or the fixed water temperature; parent has no explicit value (TOP76, TOP81); children: Curve points, or the fixed water temperature; command range not expanded',
    ),
    Requirement(
        when=(Condition('TOP146', 'Zone_Configuration', ('22', '38')),),
        any_of=(),
        child_topics=('TOP34', 'TOP35', 'TOP82', 'TOP83', 'TOP84', 'TOP85', 'TOP86', 'TOP87', 'TOP88', 'TOP89'),
        child_commands=('SetZ2HeatRequestTemperature', 'SetZ2CoolRequestTemperature', 'SetCurves'),
        source='SM 109-110; BA 45, 47',
        note='',
    ),
    Requirement(
        when=(Condition('TOP146', 'Zone_Configuration', ('25', '38')),),
        any_of=(),
        child_topics=('TOP153',),
        child_commands=('SetPoolDelta',),
        source='SM 100; BA 32',
        note='',
    ),
    Requirement(
        when=(Condition('TOP168', 'Cooling_Enable', ('1',)),),
        any_of=(),
        child_topics=('TOP120', 'TOP81', 'TOP24', 'TOP79', 'TOP80'),
        child_commands=('SetExternalHeatCoolControl', 'SetCoolingWaterMode', 'SetFloorCoolDelta', 'SetHeatToCoolTemp', 'SetCoolToHeatTemp', 'SetOperationMode'),
        source='SM 97-98, 106, 110, 189; BA 19, 40, 47-48',
        note='parent: Cooling (custom menu, TOP168 = 1; cooling models only); children: Heat/cool switch (TOP120), water temperature mode, curve, delta T and switch temperatures for cooling (TOP81, TOP24, TOP79, TOP80), cool operation modes; cooling models only; cool operation modes (no topic given)',
    ),
    Requirement(
        when=(Condition('TOP182', 'Extra_Pump_Use', ('2',)),),
        any_of=(),
        child_topics=('TOP183',),
        child_commands=('SetExtraPumpMode',),
        source='SM 108; BA 43',
        note='',
    ),
    Requirement(
        when=(Condition('TOP120', 'External_Heat_Cool_Control', ('1',)),),
        any_of=(),
        child_topics=(),
        child_commands=('SetMainSchedule', 'SetOperationMode'),
        source='SM 106, 190',
        note='parent: Heat/cool switch on (TOP120 = 1); children: Weekly timer and operation mode auto are not usable; children: no topic, weekly timer and operation mode auto are not usable',
    ),
)

EFFECTS: tuple[Effect, ...] = (
    Effect(
        topics=('TOP45', 'TOP25'),
        when=(Condition('TOP19', 'Holiday_Mode_State', ('2',)),),
        text='Holiday mode active (TOP19 = 2)',
        source='SM 193',
    ),
    Effect(
        topics=('TOP132',),
        when=(Condition('TOP99', 'Buffer_Installed', ('1',)),),
        text='Buffer tank connection on (TOP99 = 1)',
        source='SM 94, 184',
    ),
    Effect(
        topics=('TOP148', 'TOP68'),
        when=(Condition('TOP167', 'Backup_Heater_Enable', ('1',)),),
        text='Back-up heater enabled in the custom menu (TOP167 = 1)',
        source='SM 163, 176',
    ),
    Effect(
        topics=('TOP78', 'TOP96', 'TOP97', 'TOP98'),
        when=(Condition('TOP59', 'Room_Heater_State', ('1',)),),
        text='Heater released by the user (TOP59 = 1); not in cooling',
        source='SM 109, 155, 173',
    ),
    Effect(
        topics=('TOP171',),
        when=(),
        text='Range 5 °C up to heating OFF temperature (TOP77) - 1',
        source='SM 109; BA 46',
    ),
    Effect(
        topics=('TOP79',),
        when=(),
        text='At least 1 °C above cool to heat temperature (TOP80)',
        source='SM 161',
    ),
)

COUPLINGS: tuple[Coupling, ...] = (
    Coupling(
        topics=('TOP194', 'TOP129'),
        text='They share one terminal: switching one on switches the other off (SM 106; test unit).',
        fault=None,
        tested_on_unit=True,
    ),
    Coupling(
        topics=('TOP149', 'TOP180'),
        text='They share one terminal; setting one resets the other (SM 103). SG ready on sets the bivalent operating mode to auto (SM 105).',
        fault=None,
        tested_on_unit=False,
    ),
    Coupling(
        topics=('TOP99',),
        text='Error H43 within 5 s; it stays until reset, also after the buffer is set back (test unit).',
        fault='H43',
        tested_on_unit=True,
    ),
    Coupling(
        topics=('TOP101',),
        text='Error H28 within 5 s and the heat pump switched off; it stays until reset. With the heat pump off no error was seen (test unit).',
        fault='H28',
        tested_on_unit=True,
    ),
    Coupling(
        topics=('TOP76', 'TOP81'),
        text='The heat pump moved heating or cooling curve points; some did not return when the mode was set back (test unit).',
        fault=None,
        tested_on_unit=True,
    ),
    Coupling(
        topics=('TOP146',),
        text='The heat pump changed the zone 1 request temperatures and curve points (test unit).',
        fault=None,
        tested_on_unit=True,
    ),
    Coupling(
        topics=('TOP168',),
        text='Switching it reset the zone 1 cooling curve and the automatic heat to cool / cool to heat temperatures (TOP79, TOP80) to factory values (test unit, set on the remote controller).',
        fault=None,
        tested_on_unit=True,
    ),
    Coupling(
        topics=('TOP147',),
        text='Only 6 and 9 kW were tested, on a unit with a 9 kW heater. What a value above the installed heater does is not known.',
        fault=None,
        tested_on_unit=False,
    ),
    Coupling(
        topics=('TOP105',),
        text='The value was reverted after about 5 s (test unit).',
        fault=None,
        tested_on_unit=True,
    ),
    Coupling(
        topics=('TOP177', 'TOP178', 'TOP193', 'TOP195', 'TOP196'),
        text='Writing an offset stopped the compressor for about 4 minutes, also with an unchanged value; no error code (test unit).',
        fault=None,
        tested_on_unit=True,
    ),
    Coupling(
        topics=('TOP144',),
        text='Starts the dry concrete program and switches the heat pump on (TOP0 = 1, circulation pump on, target of the first stage); switching it off returned to the previous state (test unit, heat pump off before).',
        fault=None,
        tested_on_unit=True,
    ),
)
