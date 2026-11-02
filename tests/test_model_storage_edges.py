"""The storage tiers' safety edges: what is copied, shared, linked and deleted.

Moving and deleting model files is destructive, so these tests are about what must
*survive*: a blob another model still uses is never removed, a model is whole in at
least one tier at every step of a move, a partial copy never looks complete, and a
delete from one tier touches no other model. Everything lives in temporary directories;
Podman, Ollama and the real tier configuration are never consulted.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from crew_chief import model_storage as ms


def add_model(models_dir: Path, name: str, blobs: dict[str, bytes]) -> None:
    """A manifest whose config is the first blob and layers the rest."""
    digests = []
    for digest, data in blobs.items():
        path = models_dir / "blobs" / f"sha256-{digest}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        digests.append(f"sha256:{digest}")
    manifest = {"config": {"digest": digests[0]}, "layers": [{"digest": d} for d in digests[1:]]}
    path = ms.manifest_path(models_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")


class Tiers(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.tiers = {t: root / t for t in ("hot", "warm", "cold")}
        self.hot, self.warm, self.cold = (self.tiers[t] for t in ("hot", "warm", "cold"))

    def blob(self, tier: Path, digest: str) -> Path:
        return tier / "blobs" / f"sha256-{digest}"


class CopyIsAtomic(Tiers):
    def test_a_destination_of_the_right_size_is_not_copied_again(self):
        src, dst = self.hot / "a", self.warm / "a"
        src.parent.mkdir(parents=True)
        dst.parent.mkdir(parents=True)
        src.write_bytes(b"12345")
        dst.write_bytes(b"ABCDE")
        ms._copy(src, dst)
        self.assertEqual(dst.read_bytes(), b"ABCDE")

    def test_a_destination_of_the_wrong_size_is_replaced(self):
        src, dst = self.hot / "a", self.warm / "a"
        src.parent.mkdir(parents=True)
        dst.parent.mkdir(parents=True)
        src.write_bytes(b"12345")
        dst.write_bytes(b"ab")
        ms._copy(src, dst)
        self.assertEqual(dst.read_bytes(), b"12345")

    def test_a_link_at_the_destination_becomes_a_real_file_and_the_target_is_untouched(self):
        src, target, dst = self.hot / "a", self.cold / "t", self.warm / "a"
        for path in (src, target, dst):
            path.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"12345")
        target.write_bytes(b"12345")
        dst.symlink_to(target)
        ms._copy(src, dst)
        self.assertFalse(dst.is_symlink())
        self.assertEqual(dst.read_bytes(), b"12345")
        self.assertEqual(target.read_bytes(), b"12345")

    def test_a_short_copy_raises_and_leaves_no_partial_file_and_no_destination(self):
        src, dst = self.hot / "a", self.warm / "a"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"12345")

        def short(source, target, **kwargs):
            Path(target).write_bytes(b"123")

        with (
            mock.patch.object(ms.shutil, "copyfile", short),
            self.assertRaisesRegex(ms.StorageError, "short copy"),
        ):
            ms._copy(src, dst)
        self.assertFalse(dst.exists())
        self.assertEqual([p.name for p in dst.parent.iterdir()], [])


class SharedBlobsSurvive(Tiers):
    def setUp(self):
        super().setUp()
        add_model(self.hot, "one:1b", {"c1": b"cfg1", "w1": b"weights-one", "lic": b"license"})
        add_model(self.hot, "two:1b", {"c2": b"cfg2", "w2": b"weights-two", "lic": b"license"})

    def test_removing_a_model_keeps_a_blob_another_model_still_uses(self):
        ms._remove("one:1b", self.hot)
        self.assertFalse(self.blob(self.hot, "w1").exists())
        self.assertTrue(self.blob(self.hot, "lic").exists())
        self.assertTrue(self.blob(self.hot, "w2").exists())
        self.assertEqual(ms.list_models(self.hot), ["two:1b"])

    def test_removing_the_last_user_of_a_blob_removes_it_and_reports_the_bytes_freed(self):
        ms._remove("one:1b", self.hot)
        freed = ms._remove("two:1b", self.hot)
        self.assertEqual(freed, len(b"cfg2") + len(b"weights-two") + len(b"license"))
        self.assertEqual(list((self.hot / "blobs").iterdir()), [])

    def test_blobs_named_to_keep_are_never_removed(self):
        ms._remove("one:1b", self.hot, keep={"sha256-w1"})
        self.assertTrue(self.blob(self.hot, "w1").exists())

    def test_empty_repository_folders_are_tidied_but_the_manifests_root_stays(self):
        ms._remove("one:1b", self.hot)
        ms._remove("two:1b", self.hot)
        self.assertTrue((self.hot / "manifests").is_dir())
        self.assertEqual(ms.list_models(self.hot), [])

    def test_a_link_is_removed_without_counting_bytes_or_touching_its_target(self):
        target = self.warm / "blobs" / "sha256-w1"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"weights-one")
        real = self.blob(self.hot, "w1")
        real.unlink()
        real.symlink_to(target)
        freed = ms._remove("one:1b", self.hot)
        self.assertFalse(real.is_symlink())
        self.assertTrue(target.exists())
        self.assertEqual(freed, len(b"cfg1") + 0)

    def test_a_blob_already_missing_is_skipped(self):
        self.blob(self.hot, "w1").unlink()
        self.assertGreaterEqual(ms._remove("one:1b", self.hot), 0)


class DeleteIsScoped(Tiers):
    def setUp(self):
        super().setUp()
        add_model(self.warm, "old:1b", {"c1": b"cfg1", "w1": b"weights-old", "lic": b"license"})
        add_model(self.hot, "live:1b", {"c2": b"cfg2", "w2": b"weights-live", "lic": b"license"})
        ms.link("old:1b", self.tiers, "warm")

    def test_deleting_a_model_that_is_not_in_the_tier_is_refused_and_removes_nothing(self):
        with self.assertRaisesRegex(ms.StorageError, "not in cold"):
            ms.delete("old:1b", self.tiers, "cold")
        self.assertTrue(ms.manifest_path(self.warm, "old:1b").is_file())

    def test_deleting_from_hot_removes_only_that_models_unshared_files(self):
        freed = ms.delete("live:1b", self.tiers, "hot")
        self.assertGreater(freed, 0)
        self.assertFalse(ms.manifest_path(self.hot, "live:1b").exists())
        self.assertTrue(ms.manifest_path(self.warm, "old:1b").is_file())
        self.assertTrue(self.blob(self.warm, "w1").exists())

    def test_deleting_from_warm_removes_the_stub_and_the_files_but_not_a_resident_models_blob(self):
        ms.delete("old:1b", self.tiers, "warm")
        self.assertFalse(ms.manifest_path(self.hot, "old:1b").exists())
        self.assertFalse(ms.manifest_path(self.warm, "old:1b").exists())
        self.assertFalse(self.blob(self.warm, "w1").exists())
        # the resident model shared the license blob and still has all of its files
        self.assertTrue(self.blob(self.hot, "lic").exists())
        self.assertTrue(self.blob(self.hot, "w2").exists())
        self.assertTrue(ms.manifest_path(self.hot, "live:1b").is_file())

    def test_a_blob_that_hot_still_links_into_the_tier_is_kept(self):
        add_model(self.warm, "other:1b", {"c3": b"cfg3", "w3": b"weights-other"})
        ms.link("other:1b", self.tiers, "warm")
        ms.delete("old:1b", self.tiers, "warm")
        self.assertTrue(self.blob(self.warm, "w3").exists())
        self.assertTrue(self.blob(self.hot, "w3").is_symlink())

    def test_a_blob_a_hot_stub_points_at_survives_even_if_its_own_manifest_is_missing_in_the_tier(
        self,
    ):
        # an interrupted move: hot has a stub for "orphan" whose manifest is not in warm,
        # and one of its blobs is the license "old" also uses
        add_model(self.hot, "orphan:1b", {"c9": b"cfg9", "lic2": b"license2"})
        shared = self.blob(self.warm, "lic")
        stub = self.blob(self.hot, "lic")
        manifest = ms.manifest_path(self.hot, "orphan:1b")
        manifest.write_text(
            json.dumps({"config": {"digest": "sha256:c9"}, "layers": [{"digest": "sha256:lic"}]})
        )
        stub.unlink()
        stub.symlink_to(shared)
        ms.delete("old:1b", self.tiers, "warm")
        self.assertTrue(
            shared.exists(), "the blob the hot stub still points at must not be deleted"
        )


class Linking(Tiers):
    def setUp(self):
        super().setUp()
        add_model(self.warm, "old:1b", {"c1": b"cfg1", "w1": b"weights-old", "lic": b"license"})
        add_model(self.hot, "live:1b", {"c2": b"cfg2", "w2": b"weights-live", "lic": b"license"})

    def test_a_stub_links_unshared_blobs_and_keeps_shared_ones_as_real_files(self):
        ms.link("old:1b", self.tiers, "warm")
        self.assertTrue(self.blob(self.hot, "w1").is_symlink())
        self.assertEqual(Path(self.blob(self.hot, "w1").readlink()), self.blob(self.warm, "w1"))
        self.assertFalse(self.blob(self.hot, "lic").is_symlink())
        self.assertTrue(self.blob(self.hot, "lic").exists())

    def test_a_shared_blob_that_was_a_link_becomes_a_real_file_again(self):
        self.blob(self.hot, "lic").unlink()
        self.blob(self.hot, "lic").symlink_to(self.blob(self.warm, "lic"))
        ms.link("old:1b", self.tiers, "warm")
        self.assertFalse(self.blob(self.hot, "lic").is_symlink())

    def test_linking_reports_the_bytes_it_freed_from_hot(self):
        add_model(self.hot, "old:1b", {"c1": b"cfg1", "w1": b"weights-old", "lic": b"license"})
        freed = ms.link("old:1b", self.tiers, "warm")
        self.assertEqual(freed, len(b"cfg1") + len(b"weights-old"))

    def test_is_linked_is_false_until_a_complete_stub_exists_and_true_after(self):
        self.assertFalse(ms.is_linked("old:1b", self.tiers, "warm"))
        ms.link("old:1b", self.tiers, "warm")
        self.assertTrue(ms.is_linked("old:1b", self.tiers, "warm"))

    def test_a_stub_with_a_blob_pointing_elsewhere_is_not_linked(self):
        ms.link("old:1b", self.tiers, "warm")
        path = self.blob(self.hot, "w1")
        path.unlink()
        path.symlink_to(self.blob(self.cold, "w1"))
        self.assertFalse(ms.is_linked("old:1b", self.tiers, "warm"))

    def test_a_stub_missing_a_shared_blob_is_not_linked(self):
        ms.link("old:1b", self.tiers, "warm")
        self.blob(self.hot, "lic").unlink()
        self.assertFalse(ms.is_linked("old:1b", self.tiers, "warm"))

    def test_resident_models_are_those_whose_files_really_live_on_hot(self):
        ms.link("old:1b", self.tiers, "warm")
        self.assertEqual(ms.resident(self.tiers), {"live:1b"})

    def test_links_into_a_tier_need_a_blobs_folder(self):
        self.assertEqual(ms._linked_into(self.hot / "absent", self.warm), set())
        ms.link("old:1b", self.tiers, "warm")
        self.assertEqual(ms._linked_into(self.hot, self.warm), {"sha256-c1", "sha256-w1"})


class Transfer(Tiers):
    def setUp(self):
        super().setUp()
        add_model(self.hot, "m:1b", {"c": b"cfg", "w": b"weights"})

    def test_a_missing_source_is_refused_before_anything_is_copied(self):
        with self.assertRaisesRegex(ms.StorageError, "not in warm"):
            ms.transfer("m:1b", self.tiers, "warm", "cold")
        self.assertEqual(ms.list_models(self.cold), [])

    def test_a_move_down_leaves_the_model_whole_in_the_target_and_a_stub_in_hot(self):
        ms.transfer("m:1b", self.tiers, "hot", "warm")
        self.assertEqual(ms.list_models(self.warm), ["m:1b"])
        self.assertTrue(ms.is_linked("m:1b", self.tiers, "warm"))
        self.assertEqual(self.blob(self.warm, "w").read_bytes(), b"weights")

    def test_a_move_back_up_replaces_the_stub_with_real_files_and_empties_the_tier(self):
        ms.transfer("m:1b", self.tiers, "hot", "warm")
        ms.transfer("m:1b", self.tiers, "warm", "hot")
        self.assertFalse(self.blob(self.hot, "w").is_symlink())
        self.assertEqual(self.blob(self.hot, "w").read_bytes(), b"weights")
        self.assertEqual(ms.list_models(self.warm), [])

    def test_an_interrupted_move_leaves_the_model_whole_in_the_source(self):
        with mock.patch.object(ms, "link", side_effect=OSError("disk gone")):
            with self.assertRaises(OSError):
                ms.transfer("m:1b", self.tiers, "hot", "warm")
        self.assertEqual(self.blob(self.hot, "w").read_bytes(), b"weights")
        self.assertTrue(ms.manifest_path(self.hot, "m:1b").is_file())


class Repair(Tiers):
    def test_a_model_in_two_lower_tiers_stays_in_the_slower_one(self):
        for tier in (self.warm, self.cold):
            add_model(tier, "m:1b", {"c": b"cfg", "w": b"weights"})
        done = ms.repair(self.tiers)
        self.assertEqual(ms.list_models(self.warm), [])
        self.assertEqual(ms.list_models(self.cold), ["m:1b"])
        self.assertTrue(any("removed leftover copy in warm" in line for line in done))
        self.assertTrue(ms.is_linked("m:1b", self.tiers, "cold"))

    def test_a_healthy_layout_needs_no_repair(self):
        add_model(self.warm, "m:1b", {"c": b"cfg", "w": b"weights"})
        ms.link("m:1b", self.tiers, "warm")
        self.assertEqual(ms.repair(self.tiers), [])


class Configuration(unittest.TestCase):
    def write(self, text: str) -> Path:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "storage.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_missing_file_says_where_to_create_it(self):
        with self.assertRaisesRegex(ms.StorageError, "no storage tiers configured"):
            ms.load_tiers(Path("/nonexistent/storage.toml"))

    def test_unknown_or_missing_tiers_are_refused_by_name(self):
        with self.assertRaisesRegex(ms.StorageError, "unknown tier.*frozen"):
            ms.load_tiers(self.write('[tiers]\nwarm = "/w"\ncold = "/c"\nfrozen = "/f"\n'))
        with self.assertRaisesRegex(ms.StorageError, r"needs cold"):
            ms.load_tiers(self.write('[tiers]\nwarm = "/w"\n'))

    def test_hot_defaults_to_the_ollama_volume_and_paths_are_expanded(self):
        tiers = ms.load_tiers(
            self.write('[tiers]\nwarm = "~/w"\ncold = "/c"\n'), hot=lambda: Path("/volume/models")
        )
        self.assertEqual(list(tiers), ["hot", "warm", "cold"])
        self.assertEqual(tiers["hot"], Path("/volume/models"))
        self.assertEqual(tiers["warm"], Path("~/w").expanduser())

    def test_a_configured_hot_is_not_overridden(self):
        called = mock.Mock()
        tiers = ms.load_tiers(
            self.write('[tiers]\nhot = "/h"\nwarm = "/w"\ncold = "/c"\n'), hot=called
        )
        self.assertEqual(tiers["hot"], Path("/h"))
        called.assert_not_called()

    def test_a_configured_hot_works_on_a_machine_without_the_podman_volume(self):
        def no_volume():
            raise ms.StorageError("cannot find the volume")

        tiers = ms.load_tiers(
            self.write('[tiers]\nhot = "/h"\nwarm = "/w"\ncold = "/c"\n'), hot=no_volume
        )
        self.assertEqual(tiers["hot"], Path("/h"))

    def test_the_volume_lookup_reports_a_missing_podman_or_volume(self):
        with mock.patch.object(ms.subprocess, "run", return_value=mock.Mock(stdout="/vol\n")):
            self.assertEqual(ms.hot_dir(), Path("/vol/models"))
        for error in (OSError("no podman"), subprocess.CalledProcessError(125, "podman")):
            with (
                self.subTest(error=type(error).__name__),
                mock.patch.object(ms.subprocess, "run", side_effect=error),
                self.assertRaisesRegex(ms.StorageError, "cannot find the .* volume"),
            ):
                ms.hot_dir()


class State(unittest.TestCase):
    def test_unreadable_or_corrupt_state_is_empty_not_an_error(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(ms.load_state(Path(tmp) / "absent.json"), {})
            bad = Path(tmp) / "bad.json"
            bad.write_text("{broken", encoding="utf-8")
            self.assertEqual(ms.load_state(bad), {})

    def test_saving_is_atomic_sorted_and_creates_the_folder(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep" / "state.json"
            ms.save_state({"b": {"tier": "warm"}, "a": {"tier": "hot"}}, path)
            self.assertEqual(list(json.loads(path.read_text())), ["a", "b"])
            self.assertEqual([p.name for p in path.parent.iterdir()], ["state.json"])
            self.assertEqual(ms.load_state(path)["b"], {"tier": "warm"})

    def test_a_model_that_disappeared_is_dropped_and_a_new_tier_restarts_the_clock(self):
        from datetime import date

        state = {
            "gone:1b": {"tier": "warm", "since": "2026-01-01"},
            "moved:1b": {"tier": "warm", "since": "2026-01-01"},
            "same:1b": {"tier": "warm", "since": "2026-01-01"},
        }
        where = {"moved:1b": "cold", "same:1b": "warm", "new:1b": "hot"}
        synced = ms.sync_state(state, where, date(2026, 11, 2))
        self.assertNotIn("gone:1b", synced)
        self.assertEqual(synced["moved:1b"], {"tier": "cold", "since": "2026-11-02"})
        self.assertEqual(synced["same:1b"]["since"], "2026-01-01")
        self.assertEqual(synced["new:1b"], {"tier": "hot", "since": "2026-11-02"})


class Unload(unittest.TestCase):
    def test_an_unreachable_ollama_is_ignored(self):
        with mock.patch.object(ms.urllib.request, "urlopen", side_effect=OSError("down")):
            ms.unload("http://h:1", "m:1b")

    def test_the_model_is_asked_to_unload_with_a_zero_keep_alive(self):
        with mock.patch.object(ms.urllib.request, "urlopen") as urlopen:
            ms.unload("http://h:1", "m:1b")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://h:1/api/generate")
        self.assertEqual(json.loads(request.data), {"model": "m:1b", "keep_alive": 0})


if __name__ == "__main__":
    unittest.main()
