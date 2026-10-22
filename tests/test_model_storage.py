"""Tests for crew_chief.model_storage — offline, on fake Ollama model directories."""

from __future__ import annotations

import json
import os
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from crew_chief import model_storage as ms
from crew_chief.serving_policy import (
    DEFAULT_ROTATION,
    ModelPolicy,
    PolicyError,
    ServingPolicy,
    load_policy,
)

TODAY = date(2026, 10, 22)


def _add_model(models_dir: Path, name: str, blobs: dict[str, bytes]) -> None:
    """Write a manifest whose config is the first blob and layers the rest."""
    digests = []
    for digest, data in blobs.items():
        path = models_dir / "blobs" / f"sha256-{digest}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        digests.append(f"sha256:{digest}")
    manifest = {
        "config": {"digest": digests[0]},
        "layers": [
            {"digest": d, "mediaType": "application/vnd.ollama.image.model"} for d in digests[1:]
        ],
    }
    path = ms.manifest_path(models_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _policy(**statuses: str) -> ServingPolicy:
    models = {n: ModelPolicy(name=n, status=s) for n, s in statuses.items()}
    return ServingPolicy(models=models)


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        self.tiers = {t: root / t for t in ("hot", "warm", "cold")}
        self.hot, self.warm, self.cold = (self.tiers[t] for t in ("hot", "warm", "cold"))
        _add_model(self.hot, "old:latest", {"c1": b"cfg", "w1": b"weights-old", "lic": b"license"})
        _add_model(self.hot, "keep:7b", {"c2": b"cfg2", "w2": b"weights-keep", "lic": b"license"})

    def tearDown(self):
        self._tmp.cleanup()

    def blob(self, tier: Path, digest: str) -> Path:
        return tier / "blobs" / f"sha256-{digest}"

    def test_list_models_names_library_models_like_ollama(self):
        self.assertEqual(ms.list_models(self.hot), ["keep:7b", "old:latest"])
        self.assertEqual(ms.list_models(self.warm), [])

    def test_moving_down_leaves_a_linked_stub_in_hot(self):
        freed = ms.transfer("old", self.tiers, "hot", "warm")
        # Ollama still lists it, and its own weights are now links into warm.
        self.assertEqual(ms.list_models(self.hot), ["keep:7b", "old:latest"])
        self.assertEqual(ms.list_models(self.warm), ["old:latest"])
        for digest in ("c1", "w1"):
            hot_blob = self.blob(self.hot, digest)
            self.assertTrue(hot_blob.is_symlink())
            self.assertEqual(Path(os.readlink(hot_blob)), self.blob(self.warm, digest))
        self.assertEqual(self.blob(self.hot, "w1").read_bytes(), b"weights-old")
        # The license blob keep:7b uses stays a real file in hot.
        self.assertFalse(self.blob(self.hot, "lic").is_symlink())
        self.assertEqual(self.blob(self.warm, "lic").read_bytes(), b"license")
        self.assertEqual(freed, len(b"cfg") + len(b"weights-old"))
        self.assertTrue(ms.is_linked("old:latest", self.tiers, "warm"))
        self.assertEqual(ms.resident(self.tiers), {"keep:7b"})

    def test_moving_further_down_repoints_the_stub(self):
        ms.transfer("old:latest", self.tiers, "hot", "warm")
        freed = ms.transfer("old:latest", self.tiers, "warm", "cold")
        self.assertEqual(ms.list_models(self.warm), [])
        self.assertEqual(list((self.warm / "blobs").iterdir()), [])
        self.assertEqual(Path(os.readlink(self.blob(self.hot, "w1"))), self.blob(self.cold, "w1"))
        self.assertEqual(self.blob(self.hot, "w1").read_bytes(), b"weights-old")
        self.assertEqual(freed, len(b"cfg") + len(b"weights-old") + len(b"license"))
        self.assertEqual(ms.locate(self.tiers)["old:latest"], "cold")

    def test_restoring_replaces_links_with_real_files(self):
        ms.transfer("old:latest", self.tiers, "hot", "warm")
        ms.transfer("old:latest", self.tiers, "warm", "hot")
        self.assertEqual(ms.list_models(self.warm), [])
        self.assertEqual(list((self.warm / "blobs").iterdir()), [])
        for digest in ("c1", "w1", "lic"):
            self.assertFalse(self.blob(self.hot, digest).is_symlink())
        self.assertEqual(self.blob(self.hot, "w1").read_bytes(), b"weights-old")
        self.assertEqual(ms.locate(self.tiers)["old:latest"], "hot")

    def test_transfer_of_missing_model_fails_without_changes(self):
        with self.assertRaises(ms.StorageError):
            ms.transfer("ghost:1b", self.tiers, "hot", "warm")
        self.assertFalse(self.warm.exists())

    def test_delete_from_the_bottom_removes_the_stub_and_keeps_shared_blobs(self):
        ms.transfer("old:latest", self.tiers, "hot", "cold")
        ms.delete("old:latest", self.tiers, "cold")
        self.assertEqual(ms.list_models(self.hot), ["keep:7b"])
        self.assertEqual(ms.list_models(self.cold), [])
        self.assertFalse(
            self.blob(self.hot, "w1").is_symlink() or self.blob(self.hot, "w1").exists()
        )
        self.assertEqual(self.blob(self.hot, "lic").read_bytes(), b"license")
        self.assertEqual(list((self.cold / "blobs").iterdir()), [])

    def test_delete_of_a_hot_model_keeps_blobs_other_models_use(self):
        ms.delete("old:latest", self.tiers, "hot")
        self.assertEqual(ms.list_models(self.hot), ["keep:7b"])
        self.assertTrue(self.blob(self.hot, "lic").exists())
        self.assertFalse(self.blob(self.hot, "w1").exists())

    def test_a_blob_linked_by_another_stub_survives_its_tier_cleanup(self):
        # Two retired models share a weights blob; the first moves on to cold
        # while the second still links to warm's copy.
        _add_model(self.hot, "twin:latest", {"c3": b"cfg3", "w1": b"weights-old"})
        ms.transfer("old:latest", self.tiers, "hot", "warm")
        ms.transfer("twin:latest", self.tiers, "hot", "warm")
        ms.transfer("old:latest", self.tiers, "warm", "cold")
        self.assertEqual(self.blob(self.hot, "c3").read_bytes(), b"cfg3")
        self.assertTrue(self.blob(self.warm, "w1").exists())

    def test_repair_links_models_moved_without_stubs_and_finishes_moves(self):
        # Moved before stubs existed: in warm, gone from hot.
        _add_model(self.warm, "legacy:latest", {"c9": b"cfg9", "w9": b"weights-9"})
        # Interrupted warm -> cold move: whole in both tiers.
        ms.transfer("old:latest", self.tiers, "hot", "warm")
        _add_model(self.cold, "old:latest", {"c1": b"cfg", "w1": b"weights-old", "lic": b"license"})
        done = ms.repair(self.tiers)
        self.assertIn("legacy:latest: linked into Ollama from warm", done)
        self.assertIn("old:latest: removed leftover copy in warm", done)
        self.assertTrue(ms.is_linked("legacy:latest", self.tiers, "warm"))
        self.assertTrue(ms.is_linked("old:latest", self.tiers, "cold"))
        self.assertNotIn("old:latest", ms.list_models(self.warm))
        self.assertEqual(ms.repair(self.tiers), [])

    def test_locate_reports_where_the_files_live(self):
        ms.transfer("old:latest", self.tiers, "hot", "warm")
        self.assertEqual(ms.locate(self.tiers), {"keep:7b": "hot", "old:latest": "warm"})


class ConfigTests(unittest.TestCase):
    def test_load_tiers_reads_paths_and_defaults_hot_to_the_volume(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "storage.toml"
            path.write_text('[tiers]\nwarm = "/w"\ncold = "/c"\n', encoding="utf-8")
            tiers = ms.load_tiers(path, hot=lambda: Path("/vol/models"))
        self.assertEqual(
            tiers, {"hot": Path("/vol/models"), "warm": Path("/w"), "cold": Path("/c")}
        )

    def test_load_tiers_requires_the_file_and_every_lower_tier(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "storage.toml"
            with self.assertRaises(ms.StorageError):
                ms.load_tiers(path, hot=lambda: Path("/v"))
            path.write_text('[tiers]\nwarm = "/w"\n', encoding="utf-8")
            with self.assertRaisesRegex(ms.StorageError, "cold"):
                ms.load_tiers(path, hot=lambda: Path("/v"))

    def test_sync_state_starts_the_clock_on_a_tier_change_only(self):
        state = {"a:1": {"tier": "warm", "since": "2026-01-01", "last_benched": "2026-02-01"}}
        synced = ms.sync_state(state, {"a:1": "warm", "b:1": "hot"}, TODAY)
        self.assertEqual(synced["a:1"]["since"], "2026-01-01")
        self.assertEqual(synced["b:1"], {"tier": "hot", "since": "2026-10-22"})
        moved = ms.sync_state(state, {"a:1": "cold"}, TODAY)
        self.assertEqual(moved["a:1"]["since"], "2026-10-22")
        self.assertEqual(moved["a:1"]["last_benched"], "2026-02-01")


class RotationTests(unittest.TestCase):
    def test_retired_models_leave_hot_storage(self):
        policy = _policy(**{"old:latest": "retired", "keep:7b": "default"})
        state = {
            "old:latest": {"tier": "hot", "since": "2026-10-22"},
            "keep:7b": {"tier": "hot", "since": "2026-01-01"},
        }
        actions, notes = ms.plan(policy, state, TODAY)
        self.assertEqual(
            [(a.kind, a.model, a.source, a.target) for a in actions],
            [("move", "old:latest", "hot", "warm")],
        )
        self.assertEqual(notes, [])

    def test_models_fall_a_tier_then_get_deleted_on_schedule(self):
        policy = _policy(**{"w:1": "retired", "w:2": "retired", "c:1": "retired", "c:2": "retired"})
        state = {
            "w:1": {"tier": "warm", "since": "2026-07-24"},  # 90 days
            "w:2": {"tier": "warm", "since": "2026-07-25"},  # 89 days
            "c:1": {"tier": "cold", "since": "2026-04-25"},  # 180 days
            "c:2": {"tier": "cold", "since": "2026-10-01"},
        }
        actions, _ = ms.plan(policy, state, TODAY)
        self.assertEqual(
            [(a.kind, a.model, a.target) for a in actions],
            [("delete", "c:1", None), ("move", "w:1", "cold")],
        )

    def test_a_model_un_retired_below_hot_is_flagged_not_moved(self):
        policy = _policy(**{"back:1": "beta"})
        actions, notes = ms.plan(policy, {"back:1": {"tier": "cold", "since": "2025-01-01"}}, TODAY)
        self.assertEqual(actions, [])
        self.assertIn("storage restore back:1", notes[0])

    def test_bench_cadence_slows_as_models_fall(self):
        policy = _policy()
        state = {
            "hot:1": {"tier": "hot"},
            "never:1": {"tier": "warm"},
            "warm-fresh:1": {"tier": "warm", "last_benched": "2026-10-01"},  # 21 days
            "warm-stale:1": {"tier": "warm", "last_benched": "2026-09-22"},  # 30 days
            "cold-fresh:1": {"tier": "cold", "last_benched": "2026-08-01"},  # 82 days
            "cold-stale:1": {"tier": "cold", "last_benched": "2026-07-24"},  # 90 days
        }
        self.assertEqual(
            ms.due(policy, state, TODAY),
            [("cold-stale:1", "cold"), ("never:1", "warm"), ("warm-stale:1", "warm")],
        )

    def test_execute_records_the_new_tier_and_deletion(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            tiers = {t: root / t for t in ("hot", "warm", "cold")}
            _add_model(tiers["hot"], "old:latest", {"c": b"c", "w": b"w"})
            state = {"old:latest": {"tier": "hot", "since": "2026-01-01"}}
            unloaded = []
            ms.execute(
                ms.Action("move", "old:latest", "hot", "warm", "retired"),
                tiers,
                state,
                TODAY,
                before_leaving_hot=unloaded.append,
            )
            self.assertEqual(unloaded, ["old:latest"])
            self.assertEqual(state["old:latest"], {"tier": "warm", "since": "2026-10-22"})
            ms.execute(ms.Action("delete", "old:latest", "warm", None, "x"), tiers, state, TODAY)
            self.assertEqual(state, {})
            self.assertEqual(ms.list_models(tiers["warm"]), [])


class PolicyRotationTests(unittest.TestCase):
    def _load(self, body: str):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.toml"
            path.write_text(body, encoding="utf-8")
            return load_policy(path)

    def test_defaults_apply_when_the_section_is_absent(self):
        self.assertEqual(self._load("").rotation, DEFAULT_ROTATION)

    def test_a_tier_can_override_one_rule(self):
        rotation = self._load("[rotation.warm]\nbench_every_days = 14\n").rotation
        self.assertEqual(rotation["warm"].bench_every_days, 14)
        self.assertEqual(rotation["warm"].demote_after_days, 90)

    def test_invalid_rotation_is_rejected(self):
        for body in (
            "[rotation.lukewarm]\nbench_every_days = 1\n",
            "[rotation.warm]\nbench_every_days = 0\n",
            "[rotation.warm]\nevery = 3\n",
            "[rotation.cold]\ndemote_after_days = 30\n",
            "[rotation.warm]\ndelete_after_days = 30\n",
        ):
            with self.subTest(body=body), self.assertRaises(PolicyError):
                self._load(body)

    def test_tracked_policy_sets_a_slowing_cadence(self):
        rotation = load_policy().rotation
        cadence = [rotation[t].bench_every_days for t in ("hot", "warm", "cold")]
        self.assertEqual(cadence, sorted(cadence))


if __name__ == "__main__":
    unittest.main()
