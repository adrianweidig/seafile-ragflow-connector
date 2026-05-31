from __future__ import annotations

import unittest
from importlib import resources

import seafile_ragflow_connector.dashboard as dashboard_package
from seafile_ragflow_connector.dashboard.ui import DASHBOARD_HTML


class DashboardUiTests(unittest.TestCase):
    def test_dashboard_html_is_loaded_from_packaged_asset(self) -> None:
        asset = resources.files(dashboard_package).joinpath("assets/dashboard.html")
        self.assertTrue(asset.is_file())
        self.assertEqual(asset.read_text(encoding="utf-8"), DASHBOARD_HTML)

    def test_long_table_cells_are_expandable_and_accessible(self) -> None:
        self.assertIn("function longText", DASHBOARD_HTML)
        self.assertIn("aria-expanded", DASHBOARD_HTML)
        self.assertIn("aria-controls", DASHBOARD_HTML)
        self.assertIn("cell-toggle", DASHBOARD_HTML)
        self.assertIn("Mehr", DASHBOARD_HTML)
        self.assertIn("Weniger", DASHBOARD_HTML)

    def test_dense_tables_have_explicit_width_controls(self) -> None:
        self.assertIn("#log-table { min-width: 1120px; }", DASHBOARD_HTML)
        self.assertIn("#change-table { min-width: 1360px; }", DASHBOARD_HTML)
        self.assertIn("#sync-table { min-width: 1180px; }", DASHBOARD_HTML)
        self.assertIn("#openwebui-table { min-width: 1420px; }", DASHBOARD_HTML)
        self.assertIn("#log-table th:nth-child(5) { width: 40%; }", DASHBOARD_HTML)

    def test_openwebui_tab_is_present(self) -> None:
        self.assertIn('data-tab="openwebui"', DASHBOARD_HTML)
        self.assertIn("/api/openwebui/status", DASHBOARD_HTML)
        self.assertIn("OpenWebUI Integration", DASHBOARD_HTML)

    def test_health_cards_show_transport_scheme(self) -> None:
        self.assertIn("health-transport", DASHBOARD_HTML)
        self.assertIn("transport-badge", DASHBOARD_HTML)
        self.assertIn("Fallback nach HTTPS-Fehler", DASHBOARD_HTML)

    def test_dashboard_has_client_side_language_switch(self) -> None:
        self.assertIn("connector-dashboard-language", DASHBOARD_HTML)
        self.assertIn("navigator.language", DASHBOARD_HTML)
        self.assertIn("Deutsch", DASHBOARD_HTML)
        self.assertIn("English", DASHBOARD_HTML)
        self.assertIn("Español", DASHBOARD_HTML)
        self.assertIn("Français", DASHBOARD_HTML)
        self.assertIn("العربية", DASHBOARD_HTML)
        self.assertIn("'ar']", DASHBOARD_HTML)
        self.assertIn("dir = currentLanguage === 'ar' ? 'rtl' : 'ltr'", DASHBOARD_HTML)
        self.assertIn("LOCALE_TAGS", DASHBOARD_HTML)
        self.assertIn("'nav.overview': 'Overview'", DASHBOARD_HTML)

    def test_dashboard_has_busy_and_empty_states(self) -> None:
        self.assertIn('aria-busy="false"', DASHBOARD_HTML)
        self.assertIn("empty-state", DASHBOARD_HTML)
        self.assertIn("Die Ansicht ist geladen", DASHBOARD_HTML)
        self.assertIn("setAttribute('aria-busy', 'true')", DASHBOARD_HTML)
        self.assertIn("pendingLoad", DASHBOARD_HTML)

    def test_dashboard_controls_keep_touch_target_size(self) -> None:
        self.assertIn("min-height: 40px", DASHBOARD_HTML)
        self.assertIn("min-height: 44px", DASHBOARD_HTML)


if __name__ == "__main__":
    unittest.main()
