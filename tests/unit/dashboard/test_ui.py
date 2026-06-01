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
        self.assertIn("#workflow-table { min-width: 1380px; }", DASHBOARD_HTML)
        self.assertIn("#log-table th:nth-child(5) { width: 40%; }", DASHBOARD_HTML)

    def test_openwebui_tab_is_present(self) -> None:
        self.assertIn('data-tab="openwebui"', DASHBOARD_HTML)
        self.assertIn("/api/openwebui/status", DASHBOARD_HTML)
        self.assertIn("OpenWebUI-Integration", DASHBOARD_HTML)

    def test_workflow_tab_can_start_selected_library_sync(self) -> None:
        self.assertIn('data-tab="workflow"', DASHBOARD_HTML)
        self.assertIn("/api/workflow/libraries", DASHBOARD_HTML)
        self.assertIn("/api/workflow/run", DASHBOARD_HTML)
        self.assertIn("workflowSelected: new Set()", DASHBOARD_HTML)
        self.assertIn("function runWorkflow", DASHBOARD_HTML)
        self.assertIn("RAGFlow-Dataset und Dokumente synchronisieren", DASHBOARD_HTML)
        self.assertIn("RAGFlow-Chat und OpenWebUI-Tool/Pipe erzeugen", DASHBOARD_HTML)
        self.assertIn("'workflow.runSelected': 'Start selection'", DASHBOARD_HTML)

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

    def test_sidebar_status_survives_language_switches(self) -> None:
        self.assertIn("sidebarStatus: null", DASHBOARD_HTML)
        self.assertIn("sidebarUpdatedAt: null", DASHBOARD_HTML)
        self.assertIn("function renderSidebarStatus", DASHBOARD_HTML)
        self.assertIn("state.sidebarStatus = statusData.state", DASHBOARD_HTML)
        self.assertIn("renderSidebarStatus();", DASHBOARD_HTML)

    def test_connector_state_is_localized_client_side(self) -> None:
        self.assertIn("const CONNECTOR_STATE_LABELS", DASHBOARD_HTML)
        self.assertIn("'wartend': 'state.waiting'", DASHBOARD_HTML)
        self.assertIn("'state.waiting': 'waiting'", DASHBOARD_HTML)
        self.assertIn("function connectorStateLabel", DASHBOARD_HTML)
        self.assertIn("connectorStateLabel(state.sidebarStatus)", DASHBOARD_HTML)
        self.assertIn(
            "const connectorState = connectorStateLabel(statusData.state)",
            DASHBOARD_HTML,
        )
        self.assertIn("status(statusData.state, connectorState)", DASHBOARD_HTML)

    def test_loaded_overview_data_is_rerendered_on_language_switch(self) -> None:
        self.assertIn("overviewData: null", DASHBOARD_HTML)
        self.assertIn("systemsData: null", DASHBOARD_HTML)
        self.assertIn("workflowData: null", DASHBOARD_HTML)
        self.assertIn("function rerenderActiveData", DASHBOARD_HTML)
        self.assertIn("rerenderActiveData();", DASHBOARD_HTML)
        self.assertIn(
            "state.overviewData = { "
            "statusData, metricsData, syncs, changes, errors, warnings, health "
            "}",
            DASHBOARD_HTML,
        )
        self.assertIn("function renderOverview", DASHBOARD_HTML)
        self.assertIn("renderOverview(state.overviewData)", DASHBOARD_HTML)
        self.assertIn("function renderSystems", DASHBOARD_HTML)
        self.assertIn("renderSystems(state.systemsData)", DASHBOARD_HTML)
        self.assertIn("function renderWorkflow", DASHBOARD_HTML)
        self.assertIn("renderWorkflow(state.workflowData)", DASHBOARD_HTML)

    def test_empty_first_paint_labels_are_localized(self) -> None:
        self.assertIn("function renderEmptyStateLabels", DASHBOARD_HTML)
        self.assertIn("'status.checking': 'checking...'", DASHBOARD_HTML)
        self.assertIn("setText('last-success', t('overview.lastSuccess') + ': -')", DASHBOARD_HTML)
        self.assertIn("setText('health-summary', t('status.checking'))", DASHBOARD_HTML)
        self.assertIn("setText('problem-count', '0 ' + t('counts.entries'))", DASHBOARD_HTML)

    def test_health_messages_are_localized_client_side(self) -> None:
        self.assertIn("function healthMessage", DASHBOARD_HTML)
        self.assertIn("function healthName", DASHBOARD_HTML)
        self.assertIn("'health.dashboardOk': 'Dashboard responded.'", DASHBOARD_HTML)
        self.assertIn("'health.name.database': 'Database'", DASHBOARD_HTML)
        self.assertIn("'health.runningJobsNoneDead': 'running jobs, no dead jobs.'", DASHBOARD_HTML)
        self.assertIn("name.textContent = healthName(check)", DASHBOARD_HTML)
        self.assertIn("message.textContent = healthMessage(check)", DASHBOARD_HTML)

    def test_dashboard_qol_labels_are_localized(self) -> None:
        self.assertIn('id="refresh-label"', DASHBOARD_HTML)
        self.assertIn('id="language-label"', DASHBOARD_HTML)
        self.assertIn('data-i18n="overview.connectorState"', DASHBOARD_HTML)
        self.assertIn('data-i18n="section.syncHistory"', DASHBOARD_HTML)
        self.assertIn("'action.autoRefresh': 'Auto-refresh'", DASHBOARD_HTML)
        self.assertIn("'action.language': 'Language'", DASHBOARD_HTML)
        self.assertIn("'action.audit': 'Audit-Excel'", DASHBOARD_HTML)
        self.assertIn("'action.audit': 'Audit Excel'", DASHBOARD_HTML)
        self.assertIn("'overview.connectorState': 'Connector state'", DASHBOARD_HTML)
        self.assertIn("'overview.recentChanges': 'Newest changes'", DASHBOARD_HTML)
        self.assertIn("'overview.systemHealth': 'Systemzustand'", DASHBOARD_HTML)
        self.assertIn("'metric.libraries': 'Bibliotheken'", DASHBOARD_HTML)
        self.assertIn("'overview.knownState': 'bekannter Zustand'", DASHBOARD_HTML)
        self.assertIn("'overview.detectedEvents': 'erkannte Ereignisse'", DASHBOARD_HTML)
        self.assertIn("'overview.logWarnings': 'Warnungen im Log'", DASHBOARD_HTML)
        self.assertIn("'overview.logErrors': 'Fehler im Log'", DASHBOARD_HTML)
        self.assertIn("'overview.logWarnings': 'log-level warnings'", DASHBOARD_HTML)
        self.assertIn("'overview.logErrors': 'log-level errors'", DASHBOARD_HTML)
        self.assertIn("t('overview.logWarnings')", DASHBOARD_HTML)
        self.assertIn("t('overview.logErrors')", DASHBOARD_HTML)
        self.assertNotIn("'Log-Level warning'", DASHBOARD_HTML)
        self.assertNotIn("'Log-Level error'", DASHBOARD_HTML)
        self.assertIn("function renderRefreshOptions", DASHBOARD_HTML)
        self.assertIn("'refresh.10s': '10 seconds'", DASHBOARD_HTML)
        self.assertIn("document.querySelectorAll('[data-i18n]')", DASHBOARD_HTML)
        self.assertIn("document.querySelectorAll('[data-i18n-placeholder]')", DASHBOARD_HTML)
        self.assertIn('data-i18n="filter.type"', DASHBOARD_HTML)
        self.assertIn('data-i18n-placeholder="placeholder.changeQuery"', DASHBOARD_HTML)
        self.assertIn("'filter.search': 'Search'", DASHBOARD_HTML)
        self.assertIn("'placeholder.changeQuery': 'Path, name, error'", DASHBOARD_HTML)
        self.assertIn("'placeholder.logQuery': 'Message or component'", DASHBOARD_HTML)
        self.assertIn("'counts.logs': 'logs'", DASHBOARD_HTML)
        self.assertIn("'table.level': 'Level'", DASHBOARD_HTML)
        self.assertIn("t('table.level')", DASHBOARD_HTML)
        self.assertIn("'table.headCommit': 'Head-Commit'", DASHBOARD_HTML)
        self.assertIn("'table.datasetId': 'Datensatz-ID'", DASHBOARD_HTML)
        self.assertIn("'table.templateHash': 'Template-Hash'", DASHBOARD_HTML)
        self.assertIn("t('table.headCommit')", DASHBOARD_HTML)
        self.assertIn("t('table.datasetId')", DASHBOARD_HTML)
        self.assertIn("t('table.templateHash')", DASHBOARD_HTML)
        self.assertIn("'openwebui.datasets': 'Datasets'", DASHBOARD_HTML)
        self.assertIn("'openwebui.dataset': 'Dataset'", DASHBOARD_HTML)
        self.assertIn("t('openwebui.datasets')", DASHBOARD_HTML)
        self.assertIn("t('openwebui.dataset')", DASHBOARD_HTML)
        self.assertIn("'openwebui.knownMappings': 'known mappings'", DASHBOARD_HTML)
        self.assertIn("t('openwebui.apiFallback')", DASHBOARD_HTML)
        self.assertIn("t('openwebui.lastSuccess')", DASHBOARD_HTML)
        self.assertNotIn("metric('Datasets'", DASHBOARD_HTML)

    def test_dashboard_controls_keep_touch_target_size(self) -> None:
        self.assertIn("min-height: 40px", DASHBOARD_HTML)
        self.assertIn("min-height: 44px", DASHBOARD_HTML)


if __name__ == "__main__":
    unittest.main()
