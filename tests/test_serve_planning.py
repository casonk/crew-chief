"""Planning and launching a served model: lookups, GPU wiring, lease sizing, exec.

``serve`` replaces the process and the lease decides whether a model shares the GPU,
so the decisions around them are pinned here with every external call stubbed:
Podman, ``nvidia-smi``, the filesystem the weights live on, and ``exec`` itself.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from crew_chief import serve
from crew_chief.code_launcher import LEASE_ENV
from crew_chief.serving_policy import ModelPolicy, ServingPolicy


def _run_returning(stdout: str):
    return mock.Mock(return_value=SimpleNamespace(stdout=stdout))


class ModelsDir(unittest.TestCase):
    def test_it_is_the_models_folder_of_the_volume_mountpoint(self) -> None:
        run = _run_returning("/var/lib/vol/_data\n")
        self.assertEqual(serve.models_dir(run), Path("/var/lib/vol/_data/models"))
        argv = run.call_args.args[0]
        self.assertEqual(argv[:3], ["podman", "volume", "inspect"])
        self.assertIn(serve.MODELS_VOLUME, argv)

    def test_a_missing_podman_or_volume_is_a_serve_error_naming_the_volume(self) -> None:
        for error in (OSError("no podman"), subprocess.CalledProcessError(125, "podman")):
            with (
                self.subTest(error=type(error).__name__),
                self.assertRaises(serve.ServeError) as raised,
            ):
                serve.models_dir(mock.Mock(side_effect=error))
            self.assertIn(serve.MODELS_VOLUME, str(raised.exception))


class BlobFor(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def pull(self, repo: str, tag: str, layers, blob_digest: str | None = "abc"):
        manifest = self.root / "manifests" / "registry.ollama.ai" / repo / tag
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"layers": layers}), encoding="utf-8")
        if blob_digest:
            blob = self.root / "blobs" / f"sha256-{blob_digest}"
            blob.parent.mkdir(parents=True, exist_ok=True)
            blob.write_bytes(b"weights")
            return blob
        return None

    @staticmethod
    def layer(kind: str = "model", digest: str = "sha256:abc") -> dict:
        return {"mediaType": f"application/vnd.ollama.image.{kind}", "digest": digest}

    def test_a_bare_name_lives_under_library_and_a_missing_tag_is_latest(self) -> None:
        blob = self.pull("library/qwen3", "latest", [self.layer()])
        self.assertEqual(serve.blob_for("qwen3", self.root), blob.resolve())

    def test_a_namespaced_name_keeps_its_namespace(self) -> None:
        blob = self.pull("someone/model", "7b", [self.layer()])
        self.assertEqual(serve.blob_for("someone/model:7b", self.root), blob.resolve())

    def test_the_model_layer_is_chosen_among_the_others(self) -> None:
        blob = self.pull(
            "library/m",
            "1b",
            [self.layer("license", "sha256:lic"), self.layer("model", "sha256:abc")],
        )
        self.assertEqual(serve.blob_for("m:1b", self.root), blob.resolve())

    def test_a_storage_tier_link_is_followed_to_the_real_file(self) -> None:
        real = Path(self.tmp.name) / "elsewhere" / "weights"
        real.parent.mkdir()
        real.write_bytes(b"weights")
        link = self.root / "blobs" / "sha256-abc"
        link.parent.mkdir(parents=True)
        link.symlink_to(real)
        self.pull("library/m", "1b", [self.layer()], blob_digest=None)
        self.assertEqual(serve.blob_for("m:1b", self.root), real.resolve())

    def test_an_unpulled_or_unreadable_manifest_says_the_model_is_not_pulled(self) -> None:
        with self.assertRaisesRegex(serve.ServeError, "not pulled"):
            serve.blob_for("ghost:1b", self.root)
        manifest = self.root / "manifests" / "registry.ollama.ai" / "library" / "bad" / "1b"
        manifest.parent.mkdir(parents=True)
        for body in (
            "not json",
            "{}",
            '{"layers": []}',
            '{"layers": [{"mediaType": "x.license"}]}',
        ):
            manifest.write_text(body, encoding="utf-8")
            with self.subTest(body=body), self.assertRaisesRegex(serve.ServeError, "not pulled"):
                serve.blob_for("bad:1b", self.root)

    def test_missing_weights_name_the_file_that_is_missing(self) -> None:
        self.pull("library/m", "1b", [self.layer()], blob_digest=None)
        with self.assertRaisesRegex(serve.ServeError, "weights for m:1b are missing"):
            serve.blob_for("m:1b", self.root)


class GpuArgs(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lib = Path(self.tmp.name)

    def test_the_security_options_come_first_and_always(self) -> None:
        args = serve.gpu_args(self.lib)
        self.assertEqual(
            args[:4], ["--security-opt", "label=disable", "--security-opt", "seccomp=unconfined"]
        )

    def test_only_driver_libraries_that_exist_are_mounted_read_only(self) -> None:
        (self.lib / "libcuda.so.1").write_bytes(b"")
        (self.lib / "libnvidia-nvvm.so.4").write_bytes(b"")
        mounts = [a for a in serve.gpu_args(self.lib) if a.endswith(":ro")]
        self.assertEqual(
            sorted(m.split(":")[1] for m in mounts),
            ["/usr/local/nvidia/lib64/libcuda.so.1", "/usr/local/nvidia/lib64/libnvidia-nvvm.so.4"],
        )

    def test_a_symlinked_library_is_mounted_by_its_real_path(self) -> None:
        real = self.lib / "libcuda.so.580"
        real.write_bytes(b"")
        (self.lib / "libcuda.so.1").symlink_to(real)
        mount = next(a for a in serve.gpu_args(self.lib) if "libcuda.so.1:ro" in a)
        self.assertTrue(mount.startswith(f"{real.resolve()}:"))

    def test_only_one_real_gpucomp_file_is_mounted_and_symlinks_are_skipped(self) -> None:
        (self.lib / "libnvidia-gpucomp.so.1").symlink_to(self.lib / "libnvidia-gpucomp.so.580")
        (self.lib / "libnvidia-gpucomp.so.580").write_bytes(b"")
        (self.lib / "libnvidia-gpucomp.so.581").write_bytes(b"")
        mounts = [a for a in serve.gpu_args(self.lib) if "gpucomp" in a]
        self.assertEqual(len(mounts), 1)
        self.assertIn("libnvidia-gpucomp.so.580:/usr/local", mounts[0])

    def test_no_libraries_means_only_the_security_options_and_present_devices(self) -> None:
        args = serve.gpu_args(self.lib)
        self.assertFalse([a for a in args if a.endswith(":ro")])
        # each device flag is paired with a path that exists on this machine
        pairs = [(args[i], args[i + 1]) for i, a in enumerate(args) if a == "--device"]
        for _, path in pairs:
            self.assertTrue(Path(path).exists(), path)


class LeaseSizing(unittest.TestCase):
    def test_gpu_total_reads_the_first_line_in_mib(self) -> None:
        self.assertEqual(serve.gpu_total_mib(_run_returning("24576\n24576\n")), 24576)

    def test_an_unreadable_gpu_is_none_not_an_error(self) -> None:
        for run in (
            mock.Mock(side_effect=OSError("no nvidia-smi")),
            mock.Mock(side_effect=subprocess.CalledProcessError(9, "nvidia-smi")),
            _run_returning("not a number\n"),
            _run_returning(""),
        ):
            with self.subTest(run=run):
                self.assertIsNone(serve.gpu_total_mib(run))

    def test_a_model_that_fits_with_headroom_gets_a_sized_lease(self) -> None:
        headroom = serve.HEADROOM_MIB
        self.assertEqual(serve.lease_size(10000, 24576), ["--gpu-mib", str(10000 + headroom)])

    def test_a_model_that_only_fits_without_headroom_takes_the_whole_gpu(self) -> None:
        total = 24576
        self.assertEqual(
            serve.lease_size(total - serve.HEADROOM_MIB, total)[:2], ["--gpu-mib", str(total)]
        )
        self.assertEqual(
            serve.lease_size(total - serve.HEADROOM_MIB + 1, total), ["--gpu", "exclusive"]
        )
        self.assertEqual(serve.lease_size(total, total), ["--gpu", "exclusive"])

    def test_an_unknown_gpu_size_takes_the_whole_gpu(self) -> None:
        self.assertEqual(serve.lease_size(100, None), ["--gpu", "exclusive"])


class LeaseCommand(unittest.TestCase):
    ARGV = ["llama-server", "-m", "x"]

    def command(self, **kwargs):
        defaults = {"total_mib": 24576, "which": lambda name: "/usr/bin/ecu", "environ": {}}
        return serve.lease_command("m", self.ARGV, 10000, **{**defaults, **kwargs})

    def test_the_command_is_wrapped_in_ecu_run_after_a_double_dash(self) -> None:
        wrapped = self.command()
        self.assertEqual(wrapped[:2], ["/usr/bin/ecu", "run"])
        self.assertEqual(wrapped[-4:], ["--", *self.ARGV][-4:])
        self.assertEqual(wrapped[wrapped.index("--") + 1 :], self.ARGV)
        self.assertIn("--own-gpu-process", wrapped)
        self.assertEqual(wrapped[wrapped.index("--priority") + 1], "interactive")
        self.assertIn(str(10000 + serve.HEADROOM_MIB), wrapped)

    def test_an_existing_lease_or_an_opt_out_means_run_bare(self) -> None:
        for environ in ({LEASE_ENV: "1"}, {"CREW_CHIEF_NO_LEASE": "1"}):
            with self.subTest(environ=environ):
                self.assertIsNone(self.command(environ=environ))

    def test_without_ecu_installed_run_bare(self) -> None:
        self.assertIsNone(self.command(which=lambda name: None))

    def test_the_real_environment_is_used_when_none_is_given(self) -> None:
        with mock.patch.dict("os.environ", {"CREW_CHIEF_NO_LEASE": "1"}):
            self.assertIsNone(serve.lease_command("m", self.ARGV, 1, which=lambda n: "/ecu"))


class Plan(unittest.TestCase):
    def test_an_unlisted_model_is_refused(self) -> None:
        with self.assertRaisesRegex(serve.ServeError, "not in the serving policy"):
            serve.plan("m", None, "http://localhost:8081")

    def test_a_retired_model_points_at_restore(self) -> None:
        entry = ModelPolicy(name="m", status="retired", backend="llamacpp")
        with self.assertRaisesRegex(serve.ServeError, "storage restore"):
            serve.plan("m", entry, "http://localhost:8081")

    def test_a_llamacpp_model_is_built_from_its_blob_port_and_draft(self) -> None:
        entry = ModelPolicy(name="m", backend="llamacpp", context=4096)
        with (
            mock.patch.object(serve, "models_dir", return_value=Path("/models")) as models,
            mock.patch.object(serve, "blob_for", return_value=Path("/models/blobs/x")) as blob,
            mock.patch.object(serve, "draft_for", return_value=None),
            mock.patch.object(serve, "podman_argv", return_value=["podman"]) as argv,
        ):
            self.assertEqual(serve.plan("m", entry, "http://localhost:9090"), ["podman"])
        blob.assert_called_once_with("m", models.return_value)
        self.assertEqual(argv.call_args.args[2:4], (Path("/models/blobs/x"), 9090))


class DraftFor(unittest.TestCase):
    def setUp(self) -> None:
        from crew_chief import gguf_sources as gs
        from crew_chief import model_storage as ms

        self.gs, self.ms = gs, ms
        self.entry = ModelPolicy(name="big", backend="llamacpp", draft="small:1b", speculative="")
        self.source = gs.GgufSource("small:1b", "org/repo", "d.gguf", "0" * 64, 5, True)

    def patched(self, sources=None, tiers=None, found=Path("/g/d.gguf"), **kwargs):
        return (
            mock.patch.object(self.gs, "load_sources", return_value=sources, **kwargs),
            mock.patch.object(
                self.ms,
                "load_tiers",
                **(
                    {"side_effect": tiers}
                    if isinstance(tiers, Exception)
                    else {"return_value": tiers}
                ),
            ),
            mock.patch.object(self.gs, "find", return_value=found),
        )

    def test_an_entry_without_a_draft_needs_no_file(self) -> None:
        self.assertIsNone(serve.draft_for(ModelPolicy(name="m")))

    def test_the_downloaded_file_is_returned(self) -> None:
        a, b, c = self.patched({"small:1b": self.source}, tiers={"hot": Path("/h")})
        with a, b, c as find:
            self.assertEqual(serve.draft_for(self.entry), Path("/g/d.gguf"))
        self.assertEqual(find.call_args.args[1], {"hot": Path("/h")})

    def test_unconfigured_storage_tiers_still_find_a_hot_download(self) -> None:
        a, b, c = self.patched({"small:1b": self.source}, tiers=self.ms.StorageError("none"))
        with a, b, c as find:
            self.assertEqual(serve.draft_for(self.entry), Path("/g/d.gguf"))
        self.assertIsNone(find.call_args.args[1])

    def test_a_draft_not_in_the_sources_file_is_refused(self) -> None:
        a, b, c = self.patched({})
        with a, b, c, self.assertRaisesRegex(serve.ServeError, "not in gguf-sources.toml"):
            serve.draft_for(self.entry)

    def test_a_draft_not_yet_downloaded_says_how_to_fetch_it(self) -> None:
        a, b, c = self.patched({"small:1b": self.source}, tiers={}, found=None)
        with a, b, c, self.assertRaisesRegex(serve.ServeError, "gguf fetch small:1b"):
            serve.draft_for(self.entry)

    def test_a_broken_sources_file_is_a_serve_error(self) -> None:
        with (
            mock.patch.object(self.gs, "load_sources", side_effect=self.gs.SourceError("bad toml")),
            self.assertRaisesRegex(serve.ServeError, "bad toml"),
        ):
            serve.draft_for(self.entry)


class PlanSwap(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ServingPolicy(
            models={
                "live:1b": ModelPolicy(name="live:1b", backend="llamacpp"),
                "old:1b": ModelPolicy(name="old:1b", status="retired"),
            }
        )

    def test_each_model_comes_back_with_its_entry_weights_and_draft(self) -> None:
        with (
            mock.patch.object(serve, "models_dir", return_value=Path("/m")),
            mock.patch.object(serve, "blob_for", return_value=Path("/m/blob")),
            mock.patch.object(serve, "draft_for", return_value=None),
        ):
            planned = serve.plan_swap(["live:1b"], self.policy)
        self.assertEqual(planned, [("live:1b", self.policy.get("live:1b"), Path("/m/blob"), None)])

    def test_a_single_bad_name_refuses_the_whole_plan_before_touching_podman(self) -> None:
        models = mock.Mock()
        with mock.patch.object(serve, "models_dir", models):
            with self.assertRaisesRegex(serve.ServeError, "ghost:1b is not in the serving policy"):
                serve.plan_swap(["live:1b", "ghost:1b"], self.policy)
            with self.assertRaisesRegex(serve.ServeError, "old:1b is retired"):
                serve.plan_swap(["live:1b", "old:1b"], self.policy)
        models.assert_not_called()


class _Replaced(BaseException):
    """Raised by the exec stub: a real exec never returns."""


class Serve(unittest.TestCase):
    """``serve`` ends in exec, which replaces the process; both exec calls are stubbed."""

    def setUp(self) -> None:
        self.execvp = mock.patch("os.execvp").start()
        self.execvpe = mock.patch("os.execvpe", side_effect=_Replaced).start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(serve, "gpu_total_mib", return_value=24576).start()
        mock.patch("sys.stdout.flush").start()
        self.command = ["llama-server", "-m", "x"]

    def test_a_leased_model_runs_under_ecu_with_the_lease_marked_in_the_environment(self) -> None:
        wrapped = ["/ecu", "run", "--", *self.command]
        with (
            mock.patch.object(serve, "lease_command", return_value=wrapped) as lease,
            self.assertRaises(_Replaced),
        ):
            serve.serve(self.command, "m", 10000, leased=True)
        lease.assert_called_once_with("m", self.command, 10000, total_mib=24576)
        program, argv, env = self.execvpe.call_args.args
        self.assertEqual((program, argv), ("/ecu", wrapped))
        self.assertEqual(env[LEASE_ENV], "1")
        self.execvp.assert_not_called()

    def test_no_lease_flag_or_no_measurement_runs_the_server_directly(self) -> None:
        with mock.patch.object(serve, "lease_command") as lease:
            serve.serve(self.command, "m", 10000, leased=False)
            serve.serve(self.command, "m", None, leased=True)
            serve.serve(self.command, "m", 0, leased=True)
        lease.assert_not_called()
        self.assertEqual(self.execvp.call_count, 3)
        self.execvp.assert_called_with("llama-server", self.command)
        self.execvpe.assert_not_called()

    def test_when_ecu_declines_the_server_runs_directly(self) -> None:
        with mock.patch.object(serve, "lease_command", return_value=None):
            serve.serve(self.command, "m", 10000, leased=True)
        self.execvp.assert_called_once_with("llama-server", self.command)
        self.execvpe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
