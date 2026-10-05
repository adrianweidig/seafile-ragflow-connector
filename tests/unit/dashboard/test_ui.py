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
        self.assertIn("#openwebui-table { min-width: 1640px; }", DASHBOARD_HTML)
        self.assertIn("#workflow-table { min-width: 1880px; }", DASHBOARD_HTML)
        self.assertIn("#workflow-history-table { min-width: 940px; }", DASHBOARD_HTML)
        self.assertIn("#workflow-run-libraries { min-width: 1120px; }", DASHBOARD_HTML)
        self.assertIn("#log-table th:nth-child(5) { width: 40%; }", DASHBOARD_HTML)

    def test_openwebui_tab_is_present(self) -> None:
        self.assertIn('data-tab="openwebui"', DASHBOARD_HTML)
        self.assertIn("/api/openwebui/status", DASHBOARD_HTML)
        self.assertIn("OpenWebUI-Integration", DASHBOARD_HTML)

    def test_openwebui_tab_can_delete_target_artifacts(self) -> None:
        self.assertIn("/api/openwebui/artifacts/delete", DASHBOARD_HTML)
        self.assertIn("function openwebuiActionCell", DASHBOARD_HTML)
        self.assertIn("function runOpenWebUIDelete", DASHBOARD_HTML)
        self.assertIn("openwebuiActionRunning: null", DASHBOARD_HTML)
        self.assertIn("'table.actions': 'Aktionen'", DASHBOARD_HTML)
        self.assertIn("'table.actions': 'Actions'", DASHBOARD_HTML)
        self.assertIn("'openwebui.deletePipe': 'Pipe löschen'", DASHBOARD_HTML)
        self.assertIn("'openwebui.deleteDataset': 'Dataset löschen'", DASHBOARD_HTML)
        self.assertIn("'openwebui.deleteChat': 'Chat löschen'", DASHBOARD_HTML)
        self.assertIn("'openwebui.deletePipe': 'Delete pipe'", DASHBOARD_HTML)
        self.assertIn("library stays untouched", DASHBOARD_HTML)

    def test_administration_tab_can_start_selected_library_sync(self) -> None:
        self.assertIn('data-tab="workflow"', DASHBOARD_HTML)
        self.assertIn(">Administration</button>", DASHBOARD_HTML)
        self.assertIn("/api/workflow/libraries", DASHBOARD_HTML)
        self.assertIn("/api/workflow/run", DASHBOARD_HTML)
        self.assertIn("workflowSelected: new Set()", DASHBOARD_HTML)
        self.assertIn("function runWorkflow", DASHBOARD_HTML)
        self.assertIn("RAGFlow-Dataset und Dokumente synchronisieren", DASHBOARD_HTML)
        self.assertIn("RAGFlow-Chat und OpenWebUI-Tool/Pipe erzeugen", DASHBOARD_HTML)
        self.assertIn("'workflow.runSelected': 'Start selection'", DASHBOARD_HTML)

    def test_administration_has_guarded_global_controls(self) -> None:
        self.assertIn('id="admin-control-card"', DASHBOARD_HTML)
        self.assertIn('id="admin-start"', DASHBOARD_HTML)
        self.assertIn('id="admin-deactivate"', DASHBOARD_HTML)
        self.assertIn('id="admin-pause"', DASHBOARD_HTML)
        self.assertIn('id="admin-resume"', DASHBOARD_HTML)
        self.assertIn('id="admin-stop"', DASHBOARD_HTML)
        self.assertIn("/api/workflow/control", DASHBOARD_HTML)
        self.assertIn("'/api/workflow/control/' + action", DASHBOARD_HTML)
        self.assertIn("{ confirm: 'STOP' }", DASHBOARD_HTML)
        self.assertIn("Die Connector-Container laufen weiter", DASHBOARD_HTML)
        self.assertIn("The connector containers keep running", DASHBOARD_HTML)
        self.assertIn("$('admin-control-actions').hidden = !enabled", DASHBOARD_HTML)
        self.assertIn("$('workflow-run').hidden = !controlsAvailable", DASHBOARD_HTML)
        self.assertIn("function workflowManualRunAllowed", DASHBOARD_HTML)
        self.assertIn("if (!workflowControlEnabled()) return compactText('-');", DASHBOARD_HTML)
        self.assertIn("if (!workflowControlEnabled()) {", DASHBOARD_HTML)
        self.assertIn("state.activeTab !== 'workflow'", DASHBOARD_HTML)

    def test_all_post_requests_send_admin_action_header_and_json(self) -> None:
        self.assertIn("'X-Connector-Admin-Action': '1'", DASHBOARD_HTML)
        self.assertIn("'Content-Type': 'application/json'", DASHBOARD_HTML)
        self.assertIn("body: JSON.stringify(payload)", DASHBOARD_HTML)

    def test_admin_api_errors_use_stable_localized_codes(self) -> None:
        self.assertIn("const API_ERROR_KEYS = Object.freeze({", DASHBOARD_HTML)
        self.assertIn("function apiErrorMessage(data)", DASHBOARD_HTML)
        self.assertIn(
            "'confirmation required': 'api.confirmationRequired'",
            DASHBOARD_HTML,
        )
        self.assertIn(
            "'api.confirmationRequired': 'Diese Aktion benötigt die ausdrückliche "
            "STOP-Bestätigung.'",
            DASHBOARD_HTML,
        )
        self.assertIn(
            "'api.confirmationRequired': 'This action requires an explicit STOP "
            "confirmation.'",
            DASHBOARD_HTML,
        )
        self.assertIn(
            "'invalid workflow transition': 'api.invalidWorkflowTransition'",
            DASHBOARD_HTML,
        )
        self.assertIn("throw new Error(apiErrorMessage(data))", DASHBOARD_HTML)

    def test_libraries_expose_admin_state_parsing_and_individual_actions(self) -> None:
        self.assertIn("function libraryAdminControl", DASHBOARD_HTML)
        self.assertIn("library.admin_state || control.state", DASHBOARD_HTML)
        self.assertIn("library.admin_enabled", DASHBOARD_HTML)
        self.assertIn("library.admin_paused", DASHBOARD_HTML)
        self.assertIn("function workflowParsingCell", DASHBOARD_HTML)
        self.assertIn("parsing.total ?? parsing.tracked", DASHBOARD_HTML)
        self.assertIn("t('workflow.parseDone')", DASHBOARD_HTML)
        self.assertIn("t('workflow.parsePending')", DASHBOARD_HTML)
        self.assertIn("t('workflow.parseFailed')", DASHBOARD_HTML)
        self.assertIn("function workflowLibraryActionCell", DASHBOARD_HTML)
        self.assertIn(
            "'/api/workflow/libraries/' + encodeURIComponent(library.repo_id)",
            DASHBOARD_HTML,
        )
        self.assertIn("add('enable', 'admin.enableLibrary')", DASHBOARD_HTML)
        self.assertIn("add('disable', 'admin.disableLibrary', true)", DASHBOARD_HTML)
        self.assertIn("add('pause', 'admin.pauseLibrary')", DASHBOARD_HTML)
        self.assertIn("add('resume', 'admin.resumeLibrary')", DASHBOARD_HTML)
        self.assertIn("&& control.state === 'active'", DASHBOARD_HTML)

    def test_active_run_renders_phase_progress_libraries_and_actions(self) -> None:
        self.assertIn('id="workflow-run-panel"', DASHBOARD_HTML)
        self.assertIn('id="workflow-progress-bar"', DASHBOARD_HTML)
        self.assertIn('id="workflow-phase-list"', DASHBOARD_HTML)
        self.assertIn('id="workflow-run-libraries"', DASHBOARD_HTML)
        self.assertIn("normalizedPercent(progress.percent", DASHBOARD_HTML)
        self.assertIn("renderWorkflowPhases(result.phases)", DASHBOARD_HTML)
        self.assertIn("renderWorkflowRunLibraries(result)", DASHBOARD_HTML)
        self.assertIn("job.effective_status || job.status", DASHBOARD_HTML)
        self.assertIn("job.paused", DASHBOARD_HTML)
        self.assertIn(
            "'/api/workflow/runs/' + encodeURIComponent(state.workflowRunId)",
            DASHBOARD_HTML,
        )
        self.assertIn("workflowAction('pause')", DASHBOARD_HTML)
        self.assertIn("workflowAction('resume')", DASHBOARD_HTML)
        self.assertIn("workflowAction('stop')", DASHBOARD_HTML)
        self.assertIn("workflowAction('retry')", DASHBOARD_HTML)

    def test_recent_administrative_runs_can_be_opened_across_sessions(self) -> None:
        self.assertIn('id="workflow-history-panel"', DASHBOARD_HTML)
        self.assertIn('id="workflow-history-table"', DASHBOARD_HTML)
        self.assertIn("/api/sync-runs?limit=50&offset=0", DASHBOARD_HTML)
        self.assertIn("run.details && run.details.kind === 'workflow_parent'", DASHBOARD_HTML)
        self.assertIn("function renderWorkflowHistory", DASHBOARD_HTML)
        self.assertIn("function workflowHistoryActionCell", DASHBOARD_HTML)
        self.assertIn("button.dataset.workflowRunId = run.sync_id", DASHBOARD_HTML)
        self.assertIn("function openWorkflowRun", DASHBOARD_HTML)
        self.assertIn("state.workflowRunId = runId", DASHBOARD_HTML)
        self.assertIn(
            "localStorage.setItem('connector-dashboard-workflow-run-id', runId)",
            DASHBOARD_HTML,
        )
        self.assertIn("refreshWorkflowRun();", DASHBOARD_HTML)
        self.assertIn("'workflow.recentAdminRuns': 'Letzte administrative Läufe'", DASHBOARD_HTML)
        self.assertIn("'workflow.recentAdminRuns': 'Recent administrative runs'", DASHBOARD_HTML)
        self.assertIn("'workflow.openRun': 'Öffnen/Steuern'", DASHBOARD_HTML)
        self.assertIn("'workflow.openRun': 'Open/control'", DASHBOARD_HTML)

    def test_administration_labels_are_complete_in_german_and_english(self) -> None:
        self.assertIn("'nav.workflow': 'Administration'", DASHBOARD_HTML)
        self.assertIn("'admin.controlTitle': 'Connector-Steuerung'", DASHBOARD_HTML)
        self.assertIn("'admin.controlTitle': 'Connector control'", DASHBOARD_HTML)
        self.assertIn("'admin.deactivate': 'Automatik deaktivieren'", DASHBOARD_HTML)
        self.assertIn("'admin.deactivate': 'Deactivate automation'", DASHBOARD_HTML)
        self.assertIn(
            "'admin.disableLibraryConfirm': 'Diese Bibliothek deaktivieren?",
            DASHBOARD_HTML,
        )
        self.assertIn("'admin.disableLibraryConfirm': 'Disable this library?", DASHBOARD_HTML)
        self.assertIn("'workflow.parseProgress': 'Parsing-Fortschritt'", DASHBOARD_HTML)
        self.assertIn("'workflow.parseProgress': 'Parsing progress'", DASHBOARD_HTML)
        self.assertIn("document.querySelectorAll('[data-i18n-aria-label]')", DASHBOARD_HTML)

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
        self.assertIn("[hidden] { display: none !important; }", DASHBOARD_HTML)
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

    def test_cached_tab_data_is_rerendered_before_refresh_after_language_switch(self) -> None:
        rerender_active = DASHBOARD_HTML.split("function rerenderActiveData() {", 1)[1].split(
            "async function loadOverview() {",
            1,
        )[0]
        self.assertIn(
            "renderWorkflowHistory(state.workflowHistoryData)",
            rerender_active,
        )
        activate_tab = DASHBOARD_HTML.split("function activateTab(name) {", 1)[1].split(
            "function initThemeToggle() {",
            1,
        )[0]
        self.assertLess(
            activate_tab.index("rerenderActiveData();"),
            activate_tab.index("loadActive();"),
        )

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

    def test_dead_jobs_can_be_cleaned_from_health_card(self) -> None:
        self.assertIn("/api/jobs/dead/cleanup", DASHBOARD_HTML)
        self.assertIn("function cleanupDeadJobs", DASHBOARD_HTML)
        self.assertIn("jobsCleanupRunning: false", DASHBOARD_HTML)
        self.assertIn("'state.maintenance': 'maintenance required'", DASHBOARD_HTML)
        self.assertIn("'wartung erforderlich': 'state.maintenance'", DASHBOARD_HTML)
        self.assertIn("'health.cleanupDeadJobs': 'Tote Jobs bereinigen'", DASHBOARD_HTML)
        self.assertIn("'health.cleanupDeadJobs': 'Clean dead jobs'", DASHBOARD_HTML)
        self.assertIn(
            "check.name === 'sync_jobs' && Number(check.failed_jobs || 0) > 0",
            DASHBOARD_HTML,
        )
        self.assertIn("cleanupDeadJobs();", DASHBOARD_HTML)

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

    def test_dashboard_uses_quieter_operational_density(self) -> None:
        self.assertIn("grid-template-columns: 248px minmax(0, 1fr)", DASHBOARD_HTML)
        self.assertIn("min-height: 196px", DASHBOARD_HTML)
        self.assertIn("min-height: 96px", DASHBOARD_HTML)
        self.assertIn("font-size: 21px", DASHBOARD_HTML)
        self.assertIn("gap: 6px", DASHBOARD_HTML)
        self.assertIn(
            "background: color-mix(in srgb, var(--accent) 13%, var(--surface))",
            DASHBOARD_HTML,
        )
        self.assertNotIn("animation: softPulse 4.8s", DASHBOARD_HTML)
        self.assertNotIn("animation: surfaceIn 420ms", DASHBOARD_HTML)


if __name__ == "__main__":
    unittest.main()
