# heishamon-homeassistant

An integration for heatpumps handled by [heishamon](https://github.com/heishamon/HeishaMon).

## Installation

Installation should be done using [hacs](https://hacs.xyz/).
1-click: [![Open in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kamaradclimber&repository=heishamon-homeassistant&category=integration)

## Configuration

Just make sure you have an MQTT integration configured. Heishamon mqtt messages should quickly lead to auto-discovery. There is no way to configure one manually.

ℹ This integration supports any heishamon MQTT topic prefix (defaults to `panasonic_heat_pump`) and multiple heatpumps (experimental).

ℹ️ By default, all sensors related to less common setups (cooling, buffer, solar or pool) are disabled by default. They can easily enabled when looking at the "Aquarea HeatPump Indoor Unit" device under "entities not shown".

### Entities of optional parts

Entities for optional parts of an installation (DHW tank, buffer tank, solar, bivalent, SG ready, optional PCB, cooling) are disabled by default. The heat pump reports which parts are installed, and the integration follows it. The behaviour is chosen in the options of the integration (Settings > Devices & services > HeishaMon > Configure):

| Option | Part reported as installed | Part reported as not installed |
|---|---|---|
| Enable (default) | its entities are enabled | nothing |
| Unavailable | its entities are enabled | its entities are shown as unavailable |
| Disable | its entities are enabled | its entities are disabled |

Entities disabled by hand are never enabled, and an entity enabled again by hand while its part is missing is left alone. Entities are only enabled once HeishaMon has published their topic, so entities unknown to the installed firmware stay disabled. Entities without a matching part (sensor offsets, efficiency stages, anti freeze, defrost signal, ...) are enabled by hand.

### Faults

The binary sensor `Fault` is on while the heat pump reports a fault code (TOP44); its attributes hold the code and its meaning. A Repairs issue (Settings > System > Repairs) is shown at the same time and disappears when the fault is gone. Code meanings come from the error code tables of the H, J, K, L and M series service manuals.

### Entity names

Entity names no longer start with "Aquarea" (Home Assistant already shows the device name), and they start with their topic (DHW, Heater, Heating, Cooling, Bivalent, Solar, Buffer, Pool, SG ready, Zone 1/2, Sensor offset, External ...), so that related entities sort next to each other on the device page. Readbacks of settings are shown under "Diagnostic". Entity IDs do not change. Sub-devices created by earlier versions of this fork are removed; their entities move back to the heat pump first.

### Installer menu settings

Topics TOP144 to TOP196 and commands SET49 to SET104 are available as entities. Those that do not belong to an optional part (heater capacity, sensor offsets, efficiency stages, heating on/off, DHW tank switch, ...) are enabled automatically once HeishaMon publishes their topic, so they stay hidden with firmwares that do not provide them. TOP170 to TOP196 and SET56 to SET104 need a HeishaMon firmware providing them; they were tested on M series only; may work on other series, not tested there.

These commands change installer settings. Some of them have side effects in the heat pump:

- Buffer tank set to yes without a buffer sensor raises error H43, which stays until it is reset.
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
