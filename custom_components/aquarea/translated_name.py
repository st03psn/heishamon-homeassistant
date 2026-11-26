"""Entity names translated through translation_key, without the device name in front.

Home Assistant only translates entity names when ``has_entity_name`` is True, and
then puts the device name in front of the name. The entities of this integration
have always been named without it (the entity ID is set explicitly), so that
changing it would rename every entity. This mixin looks the translated name up
the same way Home Assistant does and falls back to the English name of the
entity description.
"""
from __future__ import annotations

from typing import Any


class TranslatedNameMixin:
    """Use ``component.aquarea.entity.<domain>.<translation_key>.name`` when there is one."""

    @property
    def name(self) -> Any:
        key = getattr(self, "_name_translation_key", None)
        platform_data = getattr(self, "platform_data", None)
        if key and platform_data is not None:
            translated = platform_data.platform_translations.get(key)
            if translated:
                try:
                    return translated.format(**(self.translation_placeholders or {}))
                except (KeyError, IndexError, ValueError):
                    return translated
        return super().name
