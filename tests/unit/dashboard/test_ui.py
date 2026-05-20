from __future__ import annotations

import unittest

from seafile_ragflow_connector.dashboard.ui import DASHBOARD_HTML


class DashboardUiTests(unittest.TestCase):
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
        self.assertIn("#log-table th:nth-child(5) { width: 40%; }", DASHBOARD_HTML)


if __name__ == "__main__":
    unittest.main()
