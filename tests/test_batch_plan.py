import tempfile
from pathlib import Path
import unittest
import json

from retro_doc_agent.inventory import inventory, plan_batches
from retro_doc_agent.scan import scan


class BatchPlanTests(unittest.TestCase):
    def test_inventory_includes_frontend_stylesheets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.css").write_text(".app { color: red; }\n", encoding="utf-8")
            (root / "app.scss").write_text("$color: red;\n", encoding="utf-8")

            entries, texts, excluded, unreadable = inventory(root)

        self.assertEqual([entry["path"] for entry in entries], ["app.css", "app.scss"])
        self.assertEqual(excluded, [])
        self.assertEqual(unreadable, [])
        self.assertEqual(set(texts), {"app.css", "app.scss"})

    def test_batches_are_deterministic_component_scoped_and_bounded(self):
        entries = [
            {"path": "frontend/app.ts", "bytes": 3, "lines": 1, "sha256": "a", "text": "source"},
            {"path": "backend/b.py", "bytes": 4, "lines": 2, "sha256": "b", "text": "source"},
            {"path": "backend/a.py", "bytes": 4, "lines": 2, "sha256": "c", "text": "source"},
            {"path": "backend/c.py", "bytes": 4, "lines": 3, "sha256": "d", "text": "source"},
        ]
        components = {"backend": "backend", "frontend": "frontend"}

        batches = plan_batches(entries, max_bytes=8, max_files=2, components=components)

        self.assertEqual(
            [(batch["component"], [file["path"] for file in batch["files"]]) for batch in batches],
            [
                ("backend", ["backend/a.py", "backend/b.py"]),
                ("backend", ["backend/c.py"]),
                ("frontend", ["frontend/app.ts"]),
            ],
        )
        self.assertTrue(all(batch["file_count"] <= 2 for batch in batches))
        self.assertTrue(all(batch["total_bytes"] <= 8 for batch in batches))
        self.assertTrue(all("text" not in file for batch in batches for file in batch["files"]))

    def test_rejects_batch_limit_smaller_than_a_file(self):
        entry = {"path": "large.ts", "bytes": 9, "lines": 1, "sha256": "hash"}
        with self.assertRaises(ValueError):
            plan_batches([entry], max_bytes=8, max_files=2)

    def test_scan_writes_batches_to_inventory_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "backend").mkdir()
            (source / "frontend").mkdir()
            (source / "backend" / "service.py").write_text("value = 1\n", encoding="utf-8")
            (source / "frontend" / "view.css").write_text(".view {}\n", encoding="utf-8")
            profile = root / "profile.toml"
            profile.write_text(
                '[components]\nbackend = "backend"\nfrontend = "frontend"\n'
                '[limits]\nmax_bytes = 1000\nmax_total = 10000\nmax_files = 10\n'
                '[batches]\nmax_bytes = 1000\nmax_files = 1\n',
                encoding="utf-8",
            )

            _, manifest = scan(source, root / "report", profile)

            saved_manifest = json.loads((root / "report" / "inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["batches"]), 2)
        self.assertEqual(
            {batch["component"] for batch in saved_manifest["batches"]},
            {"backend", "frontend"},
        )
        self.assertTrue(all(batch["file_count"] == 1 for batch in saved_manifest["batches"]))


if __name__ == "__main__":
    unittest.main()
