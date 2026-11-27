# heishamon-homeassistant

An integration for heatpumps handled by [heishamon](https://github.com/heishamon/HeishaMon).

## Installation

Installation should be done using [hacs](https://hacs.xyz/).
1-click: [![Open in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kamaradclimber&repository=heishamon-homeassistant&category=integration)

## Configuration

Just make sure you have an MQTT integration configured. Heishamon mqtt messages should quickly lead to auto-discovery. There is no way to configure one manually.

ℹ This integration supports any heishamon MQTT topic prefix (defaults to `panasonic_heat_pump`) and multiple heatpumps (experimental).

ℹ️ Entities of optional parts (DHW tank, buffer tank, solar, bivalent, SG ready, optional PCB, cooling) follow what the heat pump reports, see below.

## Additions in this fork

This fork (`st03psn/heishamon-homeassistant`) adds the topics and commands of an extended HeishaMon firmware (`st03psn/HeishaMon`, branch `aquarea-parity-draft`) and a few changes to the integration itself. They were tested on M series only; may work on other series, not tested there.

### Firmware compatibility

| HeishaMon firmware | What you get |
|---|---|
| Extended firmware (TOP170-TOP196, SET56-SET104) | everything below |
| Official firmware with TOP144-TOP169 and SET49-SET55 | all entities of the official firmware; the entities of the extended firmware stay disabled |
| Older official firmware | as before; newer entities stay disabled |

New entities are created disabled and are only enabled once HeishaMon has published their topic. The readbacks TOP144-TOP198 and the commands SET49-SET55 are defined as in the original integration, including which of them are enabled from the start; the fork adds the optional part they belong to and its shorter names. Commands of the extended firmware whose readback topic already exists in the official firmware (for example anti freeze, TOP109) additionally wait for a topic only the extended firmware publishes (`Static_Pressure`, TOP170). With the official firmware they therefore stay disabled. If you enable one by hand anyway, the official firmware ignores the command: nothing changes in the heat pump, and the entity falls back to the value the heat pump reports after the retries. Updating the firmware later needs no change in Home Assistant: the entities are enabled when the new topics arrive.

The parts SG ready and cooling are recognised from TOP149 and TOP168, which older firmwares do not publish. Their entities are then neither enabled nor disabled automatically.

### Firmware updates

The option *Firmware source* chooses the GitHub repository the firmware update entity takes releases from: `st03psn/HeishaMon` (this fork, the default, also for entries created before the option existed), `heishamon/HeishaMon` (the original project) or a custom `owner/repo`. Installing a release of another project replaces the firmware on the board, including its security features.

The latest release (`releases/latest` of the GitHub API, so not a prerelease) is offered. The firmware is downloaded from the release assets `HeishaMon.ino.esp32-v<version>.bin` / `.md5` (ESP32) or `HeishaMon.ino.d1-v<version>.bin` / `.md5` (ESP8266), where `<version>` is the tag without its leading `v`. Only for the original project the files in `binaries/` of its main branch are used when the release has no such assets; for any other source a missing file is an error and nothing is installed. Development builds (`Alpha-<sha>`, `Nightly-<sha>`) have no version number: the latest release is shown, but not offered as an update. Install it explicitly with the action `update.install` if wanted. A build with a suffix (`3.2.0-st03psn.1`) is not offered the release with the same numbers without a suffix (`3.2.0`), and the reverse is not offered either.

### Installation of the fork

Add `https://github.com/st03psn/heishamon-homeassistant` as a custom repository (type integration) in the Marketplace / HACS. It uses the same folder (`custom_components/aquarea`) as the original integration, so only one of the two can be installed. On Home Assistant 2026.11 and later, uninstalling the original from the Marketplace while it is set up offers only "Delete and uninstall", which also removes the setup with its devices and entities. To keep them, replace the files in `custom_components/aquarea` by hand (Samba, SSH, file editor) and restart Home Assistant; the setup, entity IDs and history stay as they are.

### Entities of optional parts

The heat pump reports which optional parts are installed: DHW tank (TOP100), buffer tank (TOP99), solar (TOP101), bivalent (TOP129), SG ready (TOP149), optional PCB (TOP110), cooling (TOP168). Solar and SG ready also need the optional PCB. Entities of a part are created disabled and follow the part. The behaviour is chosen in the options of the integration (Settings > Devices & services > HeishaMon > Configure):

| Option | Part reported as installed | Part reported as not installed |
|---|---|---|
| Enable (default) | its entities are enabled | nothing |
| Unavailable | its entities are enabled | its entities are shown as unavailable |
| Disable | its entities are enabled | its entities are disabled |

Changes are applied about 10 seconds after a message, so that the burst of messages after a start is evaluated as a whole. Entities disabled by hand are never enabled, and an entity enabled again by hand while its part is missing is left alone. Enabling entities reloads the integration once, so its entities are unavailable for a moment.

Entities that belong to no optional part (heater capacity, sensor offsets, efficiency stages, heating on/off, anti freeze, DHW tank switch, ...) are enabled once HeishaMon publishes their topic and are never disabled automatically.

### Operating state and compressor runs

The integration keeps one picture of the heat pump and derives from it:

- `Operating state`: off, idle, heating, cooling, heating water, defrosting or fault. It is unknown while HeishaMon is offline. The climate entities show the same as their current activity.
- Compressor runs: starts, run time, short runs (shorter than 10 minutes) and defrosts of today, the current and the last run time and the last pause. A defrost belongs to the run it happens in. The counters are kept across restarts; the time Home Assistant was not running is not counted as run time.
- The event entity `Compressor run` fires `started` (with the pause before it) and `finished` (with duration in minutes, defrosts, short run or not, and what the run was for).

The operating state is derived from TOP0, TOP4, TOP8, TOP20, TOP26 and TOP44. Tested on M series only; may work on other series, not tested there.

### Commands the heat pump does not take over

A command is repeated up to three times when the heat pump does not report the new value. After the last attempt a Repairs issue names the entity, and the event `aquarea_command_failed` is fired (entity, expected and reported value) for automations. The issue disappears when the next command of that entity is taken over.

### Settings that depend on other settings

The remote controller hides settings that have no effect while another setting is off (for example the delta T while the pump runs on maximum duty, or the solar deltas without a solar connection). The heat pump itself accepts such values. The integration follows the remote controller:

- A change to such a setting is refused, and the message names the setting it depends on and the value that one would need. The check can be switched off in the options of the integration.
- The sensor `Settings without effect` counts these settings; its attributes list them with the setting in the way.
- Switching a setting off, or back to its first option, is never refused.
- Entities of such settings are hidden while they have no effect and shown again once they have one (option "Hide settings that have no effect"). Entities you hid yourself stay hidden.
- Nothing is refused while the value of the parent setting is not known or HeishaMon is offline, and nothing for other series than the M series: the rules are only known to hold there.
- The value of the parent is the one HeishaMon last reported. An automation that changes a parent and its child in one go has to wait until the parent is reported back.

The rules come from the table "Settings that depend on other settings" of the HeishaMon topic documentation (service and operating manual of the M series, and the Aquarea Service Cloud on an M-series unit). Not checked this way: the operating mode, the curves and the weekly timer, because their commands also carry values the rules do not cover.

### Journal of setting changes

The integration records every change of a setting of the heat pump (the readbacks of its numbers, selects and switches): which setting, old and new value, when, and where it came from.

- `home_assistant`: the change followed a command of this integration within 60 seconds.
- `other`: everything else, such as the remote controller, the Panasonic cloud, the HeishaMon web page or rules, or the heat pump itself.

A command accounts for one change. Not recorded are states the heat pump sets back by itself: defrost, the forced runs (DHW, heater, sterilization) and the remaining time of the powerful mode.

The sensor `Last setting change` shows the newest change and lists the last 20 in its attributes; the event `aquarea_setting_changed` is fired for automations. The last 200 changes are kept across restarts and are part of the diagnostics download. Values are the raw values HeishaMon publishes. A change made while Home Assistant was not running is recorded when it is seen, with that time.

### Faults

The binary sensor `Fault` is on while the heat pump reports a fault code (TOP44); its attributes hold the code and its meaning. A Repairs issue (Settings > System > Repairs) is shown at the same time and disappears when the fault is gone. Code meanings come from the error code tables of the H, J, K, L and M series service manuals. A fault can be reset with the button `Reset fault code` (SetReset) once its cause is removed.

### Entity names

In German, names use the usual heating abbreviations: AT (Außentemperatur), VLT/RLT (Vor-/Rücklauftemperatur), WW (Warmwasser), WP (Wärmepumpe), ΔT (Spreizung). "Platine" marks functions of the real optional PCB, "EMU" the optional PCB emulated by HeishaMon, "Zone 1/2" the heating and cooling circuits. Status readbacks of a switch end in "(Status)". A name that is a single word is never abbreviated (Außentemperatur, Vorlauftemperatur).

Entity names do not start with "Aquarea" (Home Assistant already shows the device name), are kept short and start with their topic (DHW, Heater, Heating, Cooling, Bivalent, Solar, Buffer, Pool, SG ready, Zone 1/2, Sensor offset, External, Emulated PCB ...), so that related entities sort next to each other on the device page. Readbacks of settings are shown under "Diagnostic". Entity IDs do not change. A switch whose topic already has a binary sensor gets no extra "(readonly)" copy.

### Emulated optional PCB

HeishaMon can stand in for the optional PCB of the heat pump ("optional PCB emulation" in the HeishaMon settings). The entities named "Emulated PCB ..." belong to this emulation: the SG ready signal, the demand control limit and the compressor contact that HeishaMon sends in place of the PCB, and the pump, mixing valve and alarm requests the heat pump sends to it. They only work with the emulation switched on, not with a real optional PCB. The integration recognises the emulation from the optional topics HeishaMon publishes only while it emulates the PCB (retained values of an earlier emulation do not count): these entities follow it like an optional part, so with the emulation off they are disabled, shown as unavailable or left as they are, depending on the option for optional parts. HeishaMon counts as not emulating after 15 minutes of running without such a topic. The settings of a real optional PCB (SG ready mode, demand control, ...) are not affected. The values sent by HeishaMon are not reported back by the heat pump, so these entities show "unknown" until a value has been sent. The installer settings "SG ready mode" and "Demand control" (whether the heat pump uses these inputs at all) are separate entities.

### Installer menu settings

Topics TOP144 to TOP196 and commands SET49 to SET104 are available as entities. They change installer settings, and some of them have side effects in the heat pump:

- A part switched on without its sensor raises a fault that stops the heat pump and stays until it is reset: solar without solar sensor raised H28, buffer tank without buffer sensor raised H43 (M series).
- Defrost signal and bivalent control share one terminal: enabling one disables the other.
- The water temperature mode (compensation curve / direct) changes the heating and cooling curve values.
- The heat pump does not check a setting against the part it belongs to (for instance DHW settings without a DHW tank).
- Internal heater capacity offers 3, 6 and 9 kW whatever the installed heater.

### Other fixes

- The bivalent advanced start and stop temperatures (SET37, SET38) were sent to command topics HeishaMon does not know (`SetBivalentAStartTemp`, `SetBivalentAStopTemp`); they now use `SetBivalentAPStartTemp` and `SetBivalentAPStopTemp`.

To recognize models recently added upstream, use **Refresh heat pump models** on the HeishaMon device in Home Assistant. Refreshing is manual, takes effect immediately, and is retained across Home Assistant restarts.

### HeishaMon 4.4 and topic groups

HeishaMon 4.4 introduced topic groups and turns the **Installer settings** group off by default. This affects both values that already existed and new installer readbacks such as static pressure, sensor offsets and efficiency stage times:

- `Aquarea Max pump duty configured`
- `Aquarea Buffer tank` / `Buffer_Installed`
- `Aquarea DHW Installed`
- `Aquarea Pump flowrate mode` / `Aquarea Pump Flowrate Mode`
- `Aquarea Liquid Type`
- `Aquarea use external outdoor sensor`
- `Aquarea anti freeze mode`
- `Aquarea Zone 1/2 sensor setting`
- `Aquarea Heating Control`
- `Aquarea Quiet Mode Priority`
- `Aquarea DHW Sensor Selection`

If you use any of these, enable **Settings → Topic groups → Installer settings** in HeishaMon after updating. While the group is off, those topics are not published and their Home Assistant entities stop updating. Values retained on the MQTT broker may remain visible until they are replaced or removed.

The new installer entities are disabled by default in Home Assistant as well. Enable the topic group first, then enable the entities you need. The new SG Ready entities are also disabled by default because they only apply to less common external-control setups.


## Alternatives

If you own Panasonic CZ-TAW1 module and have access to Panasonic smart cloud: use [https://github.com/cjaliaga/home-assistant-aquarea](https://github.com/wpatrik14/home-assistant-aquarea) or https://github.com/ronhks/panasonic-aquarea-smart-cloud-mqtt.

⚠️ this integration and home-assistant-aquarea use the same subdirectory in `custom_components` so they cannot be installed via hacs at the same time.
Uninstall one before installing the other.

## UI

When using compensation curves method, one can add a nice card to represent the values using [ploty](Plotly Graph Card)

```
type: vertical-stack
cards:
  - type: vertical-stack
    cards:
      - type: horizontal-stack
        cards:
          - type: entities
            entities:
            - entity: number.panasonic_heat_pump_main_z1_heat_curve_outside_low_temp
              name: "x_min: Outside temp lowest point"
            - entity: number.panasonic_heat_pump_main_z1_heat_curve_target_low_temp
              name: "y_min: Target temp lowest point"
      - type: horizontal-stack
        cards:
          - type: entities
            entities:
            - entity: number.panasonic_heat_pump_main_z1_heat_curve_outside_high_temp
              name: "x_max: Outside temp highest point"
            - entity: number.panasonic_heat_pump_main_z1_heat_curve_target_high_temp
              name: "y_max: Target temp highest point"
  - type: custom:plotly-graph
    refresh_interval: 10
    title: Heat curve
    defaults:
      entity:
        show_value: true
        line:
          shape: spline
    layout:
      xaxis:
        type: number
        autorange: true
    entities:
      - entity: ''
        name: Zone 2
        x:
          - >-
            $ex
            hass.states['number.panasonic_heat_pump_main_z2_heat_curve_outside_low_temp'].state
          - >-
            $ex
            hass.states['number.panasonic_heat_pump_main_z2_heat_curve_outside_high_temp'].state
        'y':
          - >-
            $ex
            hass.states['number.panasonic_heat_pump_main_z2_heat_curve_target_high_temp'].state
          - >-
            $ex
            hass.states['number.panasonic_heat_pump_main_z2_heat_curve_target_low_temp'].state
      - entity: ''
        name: Zone 1
        x:
          - >-
            $ex
            hass.states['number.panasonic_heat_pump_main_z1_heat_curve_outside_low_temp'].state
          - >-
            $ex
            hass.states['number.panasonic_heat_pump_main_z1_heat_curve_outside_high_temp'].state
        'y':
          - >-
            $ex
            hass.states['number.panasonic_heat_pump_main_z1_heat_curve_target_high_temp'].state
          - >-
            $ex
            hass.states['number.panasonic_heat_pump_main_z1_heat_curve_target_low_temp'].state
```

## Also look at

https://github.com/waermewacht/integration is a great integration to provide in depth details about heatpump behavior, some health checks and allows to analyse heatpump performance. It detects heatpump using heishamon natively.
