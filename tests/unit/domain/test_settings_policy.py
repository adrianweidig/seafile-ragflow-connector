from __future__ import annotations

import unittest

from seafile_ragflow_connector.domain.settings_policy import evaluate_dataset_settings_change


class SettingsPolicyTests(unittest.TestCase):
    def test_first_observation_does_not_reparse(self) -> None:
        decision = evaluate_dataset_settings_change(None, "sha256:a", reparse_on_change=True)
        self.assertFalse(decision.changed)
        self.assertFalse(decision.enqueue_reparse)

    def test_changed_settings_do_not_reparse_by_default(self) -> None:
        decision = evaluate_dataset_settings_change("sha256:a", "sha256:b", reparse_on_change=False)
        self.assertTrue(decision.changed)
        self.assertFalse(decision.enqueue_reparse)

    def test_changed_settings_can_enqueue_reparse(self) -> None:
        decision = evaluate_dataset_settings_change("sha256:a", "sha256:b", reparse_on_change=True)
        self.assertTrue(decision.changed)
        self.assertTrue(decision.enqueue_reparse)


if __name__ == "__main__":
    unittest.main()
