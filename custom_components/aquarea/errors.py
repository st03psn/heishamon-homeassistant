"""Fault codes reported by the heat pump (TOP44).

English texts are the "Abnormality / Protection control" column of the error
codes table in the Panasonic service manuals of the H, J, K, L and M series
(H: PAPAMY1711064CE, J: WH-ADC0309J3E5, K: WH-ADC0912K6E5AN,
L: PAPAMY2303060CE, M: PCZ2406001CE). The codes are the same in these
manuals; where the wording differs between series, both are given. German
texts are those of the fault table in the German operating manual of the M
series where it has the code; where its numbering contradicts the service
manual (F30, F43, F45), the service manual decides. Other German texts are
translations of the English ones.
"""
from __future__ import annotations

from typing import Optional

NO_ERROR = "No error"

ERROR_CODES: dict[str, tuple[str, str]] = {
    "H00": ("No abnormality detected", "Keine Störung"),
    "H12": ("Indoor/Outdoor capacity unmatched", "Nicht passende Geräteleistungen"),
    "H15": ("Outdoor compressor temperature sensor abnormality", "Störung Kompressor-Temperaturfühler"),
    "H20": ("Water pump abnormality", "Störung Umwälzpumpe"),
    "H23": ("Indoor refrigerant liquid temperature sensor abnormality", "Störung Kältemittelfühler"),
    "H27": ("Service valve error", "Störung Serviceventil"),
    "H28": ("Abnormal solar sensor", "Störung Solarfühler"),
    "H31": ("Abnormal swimming pool sensor", "Störung Schwimmbadfühler"),
    "H36": ("Abnormal buffer tank sensor", "Störung Pufferspeicherfühler"),
    "H38": ("Brand code not match", "Markencode passt nicht"),
    "H42": ("Compressor low pressure abnormality", "Niederdruckschutz"),
    "H43": ("Abnormal Zone 1 sensor", "Störung Fühler Heizkreis 1"),
    "H44": ("Abnormal Zone 2 sensor", "Störung Fühler Heizkreis 2"),
    "H62": ("Water flow switch abnormality", "Störung wasserseitiger Strömungswächter"),
    "H63": (
        "Abnormal low pressure sensor (H/J series: refrigerant low pressure abnormality)",
        "Niederdruckfühler gestört (H/J-Serie: Kältemittel-Niederdruck gestört)",
    ),
    "H64": ("Refrigerant high pressure abnormality", "Störung Hochdrucksensor"),
    "H65": ("Abnormal deice water circulation", "Störung Wasserzirkulation während Abtauung"),
    "H67": ("Abnormal External Thermistor 1", "Störung Außentemperaturfühler 1"),
    "H68": ("Abnormal External Thermistor 2", "Störung Außentemperaturfühler 2"),
    "H70": ("Back-up heater OLP abnormality", "Störung Überlastschutz Innengeräte-E-Heizstab"),
    "H72": ("Tank sensor abnormal", "Störung WW-Speicher-Temperaturfühler 1"),
    "H74": ("PCB communication error", "Störung Platinenkommunikation"),
    "H75": ("Low water temperature control", "Niedrig-Wassertemp.-Schutz"),
    "H76": ("Indoor - control panel communication abnormality", "Kommunikation Innengerät – Bedienteil gestört"),
    "H90": ("Indoor/outdoor abnormal communication", "Komm.störung Innen- Außengerät"),
    "H91": ("Tank heater OLP abnormality", "Störung Überlastschutz WW-E-Heizstab"),
    "H95": ("Indoor/Outdoor wrong connection", "Innen- und Außengerät falsch angeschlossen"),
    "H98": ("Outdoor high pressure overload protection", "Störung wegen Hochdruckschutz"),
    "H99": ("Indoor heat exchanger freeze prevention", "Störung Frostschutz Innengeräte-Wärmetauscher"),
    "F12": ("Pressure switch activate", "Auslösung Hochdruckschalter im Außengerät"),
    "F14": ("Outdoor compressor abnormal revolution", "Falsche Verdichterdrehzahl"),
    "F15": ("Outdoor fan motor lock abnormality", "Falsche Drehzahl AG-Ventilatormotor"),
    "F16": ("Total running current protection", "Störung wg. überhöhter Stromaufnahme"),
    "F20": ("Outdoor compressor overheating protection", "Störung wg. Überlastschutz des Verdichters"),
    "F22": ("IPM (power transistor) overheating protection", "Störung wg. Überlastschutz Leistungstrans."),
    "F23": ("Outdoor Direct Current (DC) peak detection", "Störung wg. Gleichstromspitzen im AG"),
    "F24": ("Refrigeration cycle abnormality", "Störung wg. Problemen im Kältekreis"),
    "F25": ("Cooling/Heating cycle changeover abnormality", "Störung wg. Problemen mit Umschaltventil"),
    "F27": ("Pressure switch abnormality", "Störung am Hochdruckschalter im AG"),
    "F29": ("Low Discharge Superheat", "Zu geringe Überhitzung am Verdichteraustritt"),
    "F30": ("Water outlet sensor 2 abnormality", "Störung Vorlauf-Temperaturfühler 2"),
    "F32": ("Abnormal Internal Thermostat", "Interner Thermostat gestört"),
    "F36": ("Outdoor air temperature sensor abnormality", "Störung Außentemperaturfühler"),
    "F37": ("Indoor water inlet temperature sensor abnormality", "Störung Rücklauf-Temperaturfühler"),
    "F40": ("Outdoor discharge pipe temperature sensor abnormality", "Störung Heißgas-Temp.-fühler im Außengerät"),
    "F41": ("PFC control", "Fehler bei der Blindleistungskompensation"),
    "F42": ("Outdoor heat exchanger temperature sensor abnormality", "Fehler beim Wärmeaustausch-Sensor im Außengerät"),
    "F43": ("Outdoor defrost sensor abnormality", "Störung Abtau-Temp.fühler im Außengerät"),
    "F45": ("Indoor water outlet temperature sensor abnormality", "Störung Vorlauf-Temperaturfühler"),
    "F46": ("Outdoor Current Transformer open circuit", "Stromwandler-Abschaltung"),
    "F48": ("Outdoor EVA outlet temperature sensor abnormality", "Fehler beim Verdunster-Austrittstemp.fühler"),
    "F49": ("Outdoor bypass outlet temperature sensor abnormality", "Störung Bypass-Austrittstemp.fühler im AG"),
    "F95": ("Cooling high pressure overload protection", "Störung wg. HD-Schutz Kühlen im Außengerät"),
}

UNKNOWN = ("Unknown code, see the service manual", "Unbekannter Code, siehe Servicehandbuch")


def is_fault(code: Optional[str]) -> bool:
    """Return True when the heat pump reports a fault."""
    return bool(code) and code not in (NO_ERROR, "H00")


def describe(code: str, language: str = "en") -> str:
    english, german = ERROR_CODES.get(code, UNKNOWN)
    return german if language.lower().startswith("de") else english
