# heishamon-homeassistant

An integration for heatpumps handled by [heishamon](https://github.com/heishamon/HeishaMon).

## Installation

Installation should be done using [hacs](https://hacs.xyz/).
1-click: [![Open in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kamaradclimber&repository=heishamon-homeassistant&category=integration)

## Configuration

Just make sure you have an MQTT integration configured. Heishamon mqtt messages should quickly lead to auto-discovery. There is no way to configure one manually.

ℹ This integration supports any heishamon MQTT topic prefix (defaults to `panasonic_heat_pump`) and multiple heatpumps (experimental).

ℹ️ Entities of optional parts (DHW tank, buffer tank, solar, bivalent, SG ready, optional PCB, cooling) follow what the heat pump reports, see below.

## Installer settings, optional parts and faults

Topics TOP144 to TOP196 and commands SET49 to SET104 are available as entities. TOP170 to TOP196 and SET56 to SET104 were tested on M series only; may work on other series, not tested there.

### Firmware compatibility

| HeishaMon firmware | What you get |
|---|---|
| Firmware with TOP170-TOP196 and SET56-SET104 (not yet in an official release) | everything below |
| Firmware with TOP144-TOP169 and SET49-SET55 | entities up to TOP169 / SET55; newer entities stay disabled |
| Older firmware | as before; newer entities stay disabled |

New entities are created disabled and are only enabled once HeishaMon has published their topic. Commands of these firmwares whose readback topic already exists in older ones (for example anti freeze, TOP109) additionally wait for a topic only those firmwares publish (`Static_Pressure`, TOP170). With older firmwares they therefore stay disabled. If you enable one by hand anyway, an older firmware ignores the command: nothing changes in the heat pump, and the entity falls back to the value the heat pump reports after the retries. Updating the firmware later needs no change in Home Assistant: the entities are enabled when the new topics arrive.

The parts SG ready and cooling are recognised from TOP149 and TOP168, which older firmwares do not publish. Their entities are then neither enabled nor disabled automatically.

### Entities of optional parts

The heat pump reports which optional parts are installed: DHW tank (TOP100), buffer tank (TOP99), solar (TOP101), bivalent (TOP129), SG ready (TOP149), optional PCB (TOP110), cooling (TOP168). Solar and SG ready also need the optional PCB. Entities of a part are created disabled and follow the part. The behaviour is chosen in the options of the integration (Settings > Devices & services > HeishaMon > Configure):

| Option | Part reported as installed | Part reported as not installed |
|---|---|---|
| Enable (default) | its entities are enabled | nothing |
| Unavailable | its entities are enabled | its entities are shown as unavailable |
| Disable | its entities are enabled | its entities are disabled |

Changes are applied about 10 seconds after a message, so that the burst of messages after a start is evaluated as a whole. Entities disabled by hand are never enabled, and an entity enabled again by hand while its part is missing is left alone. Enabling entities reloads the integration once, so its entities are unavailable for a moment.

Entities that belong to no optional part (heater capacity, sensor offsets, efficiency stages, heating on/off, anti freeze, DHW tank switch, ...) are enabled once HeishaMon publishes their topic and are never disabled automatically.

### Faults

The binary sensor `Fault` is on while the heat pump reports a fault code (TOP44); its attributes hold the code and its meaning. A Repairs issue (Settings > System > Repairs) is shown at the same time and disappears when the fault is gone. Code meanings come from the error code tables of the H, J, K, L and M series service manuals. A fault can be reset with the button `Reset fault code` (SetReset) once its cause is removed.

### Entity names

Readbacks of settings are shown under "Diagnostic". A switch whose topic already has a binary sensor gets no extra "(readonly)" copy (it would show the same value twice).

### Emulated optional PCB

HeishaMon can stand in for the optional PCB of the heat pump ("optional PCB emulation" in the HeishaMon settings). The entities named "Emulated PCB ..." belong to this emulation: the SG ready signal, the demand control limit and the compressor contact that HeishaMon sends in place of the PCB, and the pump, mixing valve and alarm requests the heat pump sends to it. They only work with the emulation switched on, not with a real optional PCB. The values sent by HeishaMon are not reported back by the heat pump, so these entities show "unknown" until a value has been sent. The installer settings "SG ready mode" and "Demand control" (whether the heat pump uses these inputs at all) are separate entities.

### Installer menu settings

These commands change installer settings, and some of them have side effects in the heat pump:

- A part switched on without its sensor raises a fault that stops the heat pump and stays until it is reset: solar without solar sensor raised H28, buffer tank without buffer sensor raised H43 (M series).
- Defrost signal and bivalent control share one terminal: enabling one disables the other.
- The water temperature mode (compensation curve / direct) changes the heating and cooling curve values.
- The heat pump does not check a setting against the part it belongs to (for instance DHW settings without a DHW tank).
- Internal heater capacity offers 3, 6 and 9 kW whatever the installed heater.

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
