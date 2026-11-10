"""Fault codes reported by the heat pump (TOP44).

English texts are the "Abnormality / Protection control" column of the error
codes table in the Panasonic service manuals of the H, J, K, L and M series
(H: PAPAMY1711064CE, J: WH-ADC0309J3E5, K: WH-ADC0912K6E5AN,
L: PAPAMY2303060CE, M: PCZ2406001CE). The codes are the same in these
manuals; where the wording differs between series, both are given. German
texts are translations of the English ones.
"""
from __future__ import annotations

from typing import Optional

NO_ERROR = "No error"

ERROR_CODES: dict[str, tuple[str, str]] = {
    "H00": ("No abnormality detected", "Keine Störung"),
    "H12": ("Indoor/Outdoor capacity unmatched", "Leistung von Innen- und Außengerät passt nicht zusammen"),
    "H15": ("Outdoor compressor temperature sensor abnormality", "Außengerät: Verdichter-Temperaturfühler gestört"),
    "H20": ("Water pump abnormality", "Wasserpumpe gestört"),
    "H23": ("Indoor refrigerant liquid temperature sensor abnormality", "Innengerät: Fühler Kältemittel flüssig gestört"),
    "H27": ("Service valve error", "Serviceventil-Fehler"),
    "H28": ("Abnormal solar sensor", "Solarfühler gestört"),
    "H31": ("Abnormal swimming pool sensor", "Schwimmbadfühler gestört"),
    "H36": ("Abnormal buffer tank sensor", "Pufferspeicherfühler gestört"),
    "H38": ("Brand code not match", "Markencode passt nicht"),
    "H42": ("Compressor low pressure abnormality", "Verdichter: Niederdruck gestört"),
    "H43": ("Abnormal Zone 1 sensor", "Fühler Zone 1 gestört"),
    "H44": ("Abnormal Zone 2 sensor", "Fühler Zone 2 gestört"),
    "H62": ("Water flow switch abnormality", "Strömungsschalter Wasser gestört"),
    "H63": (
        "Abnormal low pressure sensor (H/J series: refrigerant low pressure abnormality)",
        "Niederdruckfühler gestört (H/J-Serie: Kältemittel-Niederdruck gestört)",
    ),
    "H64": ("Refrigerant high pressure abnormality", "Kältemittel-Hochdruck gestört"),
    "H65": ("Abnormal deice water circulation", "Wasserzirkulation beim Abtauen gestört"),
    "H67": ("Abnormal External Thermistor 1", "Externer Thermistor 1 gestört"),
    "H68": ("Abnormal External Thermistor 2", "Externer Thermistor 2 gestört"),
    "H70": ("Back-up heater OLP abnormality", "Überlastschutz Heizstab ausgelöst"),
    "H72": ("Tank sensor abnormal", "Speicherfühler gestört"),
    "H74": ("PCB communication error", "Platinen-Kommunikationsfehler"),
    "H75": ("Low water temperature control", "Regelung bei niedriger Wassertemperatur"),
    "H76": ("Indoor - control panel communication abnormality", "Kommunikation Innengerät – Bedienteil gestört"),
    "H90": ("Indoor/outdoor abnormal communication", "Kommunikation Innen-/Außengerät gestört"),
    "H91": ("Tank heater OLP abnormality", "Überlastschutz Speicher-Heizstab ausgelöst"),
    "H95": ("Indoor/Outdoor wrong connection", "Innen- und Außengerät falsch angeschlossen"),
    "H98": ("Outdoor high pressure overload protection", "Hochdruck-Überlastschutz Außengerät"),
    "H99": ("Indoor heat exchanger freeze prevention", "Frostschutz Wärmetauscher Innengerät"),
    "F12": ("Pressure switch activate", "Druckschalter ausgelöst"),
    "F14": ("Outdoor compressor abnormal revolution", "Verdichter Außengerät: unnormale Drehzahl"),
    "F15": ("Outdoor fan motor lock abnormality", "Ventilatormotor Außengerät blockiert"),
    "F16": ("Total running current protection", "Schutz Gesamtstrom"),
    "F20": ("Outdoor compressor overheating protection", "Überhitzungsschutz Verdichter Außengerät"),
    "F22": ("IPM (power transistor) overheating protection", "Überhitzungsschutz IPM (Leistungstransistor)"),
    "F23": ("Outdoor Direct Current (DC) peak detection", "Außengerät: Gleichstromspitze erkannt"),
    "F24": ("Refrigeration cycle abnormality", "Kältekreis gestört"),
    "F25": ("Cooling/Heating cycle changeover abnormality", "Umschaltung Kühlen/Heizen gestört"),
    "F27": ("Pressure switch abnormality", "Druckschalter gestört"),
    "F29": ("Low Discharge Superheat", "Zu geringe Überhitzung am Verdichteraustritt"),
    "F30": ("Water outlet sensor 2 abnormality", "Wasseraustrittsfühler 2 gestört"),
    "F32": ("Abnormal Internal Thermostat", "Interner Thermostat gestört"),
    "F36": ("Outdoor air temperature sensor abnormality", "Außentemperaturfühler gestört"),
    "F37": ("Indoor water inlet temperature sensor abnormality", "Innengerät: Wassereintrittsfühler gestört"),
    "F40": ("Outdoor discharge pipe temperature sensor abnormality", "Außengerät: Druckrohrfühler gestört"),
    "F41": ("PFC control", "PFC-Regelung"),
    "F42": ("Outdoor heat exchanger temperature sensor abnormality", "Außengerät: Wärmetauscherfühler gestört"),
    "F43": ("Outdoor defrost sensor abnormality", "Außengerät: Abtaufühler gestört"),
    "F45": ("Indoor water outlet temperature sensor abnormality", "Innengerät: Wasseraustrittsfühler gestört"),
    "F46": ("Outdoor Current Transformer open circuit", "Außengerät: Stromwandler unterbrochen"),
    "F48": ("Outdoor EVA outlet temperature sensor abnormality", "Außengerät: Verdampferaustrittsfühler gestört"),
    "F49": ("Outdoor bypass outlet temperature sensor abnormality", "Außengerät: Bypass-Austrittsfühler gestört"),
    "F95": ("Cooling high pressure overload protection", "Hochdruck-Überlastschutz Kühlen"),
}

UNKNOWN = ("Unknown code, see the service manual", "Unbekannter Code, siehe Servicehandbuch")


def is_fault(code: Optional[str]) -> bool:
    """Return True when the heat pump reports a fault."""
    return bool(code) and code not in (NO_ERROR, "H00")


def describe(code: str, language: str = "en") -> str:
    english, german = ERROR_CODES.get(code, UNKNOWN)
    return german if language.lower().startswith("de") else english
