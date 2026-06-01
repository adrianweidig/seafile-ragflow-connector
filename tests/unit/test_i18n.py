from __future__ import annotations

import unittest

from seafile_ragflow_connector.i18n import (
    LANGUAGE_LABELS,
    SUPPORTED_LANGUAGES,
    Localizer,
    detect_language,
    language_from_settings,
    normalize_language,
)


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
        self.assertEqual(normalize_language("pt_BR.UTF-8"), "pt")
        self.assertEqual(normalize_language("ar_SA.UTF-8"), "ar")

    def test_settings_without_language_keep_german_default_independent_of_host_locale(self) -> None:
        settings = type("Settings", (), {"connector_language": None})()

        self.assertEqual(language_from_settings(settings), "de")

    def test_missing_translation_keys_fall_back_to_german_key_safely(self) -> None:
        self.assertEqual(Localizer("en").text("sources.no_sources"), "No matching sources found.")
        self.assertEqual(Localizer("en").text("does.not.exist"), "does.not.exist")

    def test_unicode_and_parameters_survive_message_formatting(self) -> None:
        text = Localizer("de").text("sources.page", value="äöü ÄÖÜ ß 日本語 😀")

        self.assertIn("äöü ÄÖÜ ß 日本語 😀", text)

    def test_product_language_catalogs_cover_supported_languages(self) -> None:
        self.assertGreaterEqual(len(SUPPORTED_LANGUAGES), 10)
        for language in SUPPORTED_LANGUAGES:
            l10n = Localizer(language)
            self.assertIn(language, LANGUAGE_LABELS)
            self.assertIn("Demo", l10n.text("product.tool_name", dataset="Demo"))
            self.assertNotEqual(
                l10n.text("openwebui_artifact.searching"),
                "openwebui_artifact.searching",
            )

        self.assertIn("بحث", Localizer("ar").text("product.tool_name", dataset="Demo"))
        self.assertIn("検索", Localizer("ja").text("product.tool_name", dataset="Demo"))
        self.assertIn("Джерело", Localizer("uk").text("preview.source"))


if __name__ == "__main__":
    unittest.main()
