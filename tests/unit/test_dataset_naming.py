from __future__ import annotations

import unittest

from seafile_ragflow_connector.utils.naming import build_dataset_name, slugify


class DatasetNamingTests(unittest.TestCase):
    def test_slugifies_problematic_names(self) -> None:
        self.assertEqual(slugify("Kunden & Verträge / 2026"), "kunden-vertrage-2026")

    def test_dataset_name_contains_repo_prefix(self) -> None:
        name = build_dataset_name(
            "Kunden & Verträge / 2026",
            "2deffbac-d7be-4ace-b406-efb799083ee9",
        )
        self.assertEqual(name, "seafile__kunden-vertrage-2026__2deffbac")

    def test_dataset_name_is_truncated(self) -> None:
        name = build_dataset_name("x" * 200, "2deffbac-d7be-4ace-b406-efb799083ee9")
        self.assertLessEqual(len(name), 128)
        self.assertTrue(name.endswith("__2deffbac"))


if __name__ == "__main__":
    unittest.main()

