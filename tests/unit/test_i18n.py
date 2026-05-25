from __future__ import annotations

import unittest

from seafile_ragflow_connector.i18n import Localizer, detect_language, normalize_language


class I18nTests(unittest.TestCase):
    def test_defaults_to_german_without_reliable_locale(self) -> None:
        self.assertEqual(
            detect_language(environ={}, system_locale="C"),
            "de",
        )

    def test_explicit_language_wins_over_system_locale(self) -> None:
        self.assertEqual(
            detect_language(explicit="en-US", environ={"LANG": "de_DE.UTF-8"}),
            "en",
        )

    def test_environment_locale_is_normalized(self) -> None:
        self.assertEqual(
            detect_language(environ={"LC_ALL": "en_US.UTF-8"}, system_locale="C"),
            "en",
        )
        self.assertEqual(normalize_language("de_DE.UTF-8"), "de")

    def test_missing_translation_keys_fall_back_to_german_key_safely(self) -> None:
        self.assertEqual(Localizer("en").text("sources.no_sources"), "No matching sources found.")
        self.assertEqual(Localizer("en").text("does.not.exist"), "does.not.exist")

    def test_unicode_and_parameters_survive_message_formatting(self) -> None:
        text = Localizer("de").text("sources.page", value="äöü ÄÖÜ ß 日本語 😀")

        self.assertIn("äöü ÄÖÜ ß 日本語 😀", text)


if __name__ == "__main__":
    unittest.main()
