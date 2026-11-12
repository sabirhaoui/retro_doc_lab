import json
import tempfile
import unittest
from pathlib import Path

from retro_doc_agent.inventory import InventoryError, load_config, run_inventory


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "agent"
        self.source = self.root / "source"
        (self.repo / "config").mkdir(parents=True)
        self.source.mkdir()
        (self.source / "src").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self, **overrides):
        config = {
            "schema_version": 1,
            "source_root": str(self.source),
            "output_root": "output",
            "source_access": "read-only",
            "network": "disabled",
            "exclude": [".git", ".venv", ".env", "*.key"],
            "source_extensions": [".py"],
            "max_file_bytes": 32,
            "max_batch_bytes": 64,
            "max_batch_files": 2,
        }
        config.update(overrides)
        path = self.repo / "config" / "agent.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return load_config(path)

    def test_inventory_counts_lines_and_builds_bounded_batches(self):
        (self.source / "src" / "a.py").write_bytes(b"one\n\n")
        (self.source / "src" / "b.py").write_bytes(b"two\n")
        (self.source / "src" / "c.py").write_bytes(b"three")
        (self.source / "src" / "large.py").write_bytes(b"x" * 33)
        (self.source / "src" / "asset.py").write_bytes(b"\0binary")
        (self.source / "src" / "ignored.txt").write_text("ignored", encoding="utf-8")
        (self.source / ".venv").mkdir()
        (self.source / ".venv" / "hidden.py").write_text("hidden", encoding="utf-8")
        (self.source / "private.key").write_text("not copied", encoding="utf-8")
        original = (self.source / "src" / "a.py").read_bytes()

        config, repo = self.write_config()
        output = run_inventory(config, repo, "fixture-run")

        self.assertEqual((self.source / "src" / "a.py").read_bytes(), original)
        inventory = json.loads((output / "inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(inventory["summary"]["source_files_found"], 5)
        self.assertEqual(inventory["summary"]["inspected_files"], 3)
        self.assertEqual(inventory["summary"]["inspected_lines"], 4)
        self.assertEqual(inventory["summary"]["batch_count"], 2)
        self.assertEqual(inventory["summary"]["uninspected_files"], 2)
        self.assertTrue(all(batch["file_count"] <= 2 for batch in inventory["batches"]))
        self.assertTrue(all(batch["total_bytes"] <= 64 for batch in inventory["batches"]))
        statuses = {item["path"]: item["status"] for item in inventory["files"]}
        self.assertEqual(statuses["src/large.py"], "oversized")
        self.assertEqual(statuses["src/asset.py"], "binary")
        self.assertNotIn(".venv/hidden.py", statuses)
        self.assertNotIn("private.key", statuses)
        self.assertNotIn("not copied", (output / "inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(json.loads((output / "run.json").read_text())["status"], "partial")

    def test_rejects_output_path_outside_agent_repository(self):
        with self.assertRaises(InventoryError):
            self.write_config(output_root="../outside")

    def test_refuses_to_overwrite_an_existing_run(self):
        config, repo = self.write_config()
        run_inventory(config, repo, "same-run")
        with self.assertRaises(FileExistsError):
            run_inventory(config, repo, "same-run")

    def test_batches_do_not_mix_top_level_components(self):
        backend = self.source / "backend"
        frontend = self.source / "frontend"
        backend.mkdir()
        frontend.mkdir()
        (backend / "service.py").write_text("backend", encoding="utf-8")
        (frontend / "view.py").write_text("frontend", encoding="utf-8")
        config, repo = self.write_config()

        output = run_inventory(config, repo, "component-run")

        inventory = json.loads((output / "inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {batch["component"] for batch in inventory["batches"]},
            {"backend", "frontend"},
        )

    def test_skips_symbolic_links(self):
        target = self.source / "target.py"
        target.write_text("external", encoding="utf-8")
        link = self.source / "linked.py"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are unavailable")
        config, repo = self.write_config()

        output = run_inventory(config, repo, "symlink-run")

        inventory = json.loads((output / "inventory.json").read_text(encoding="utf-8"))
        self.assertIn("linked.py", inventory["excluded_paths"])
        self.assertNotIn("linked.py", {item["path"] for item in inventory["files"]})


if __name__ == "__main__":
    unittest.main()
