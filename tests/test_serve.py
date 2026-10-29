"""Tests for crew_chief.serve — offline, no Podman or GPU required."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crew_chief import serve
from crew_chief.cli import build_parser
from crew_chief.serving_policy import ModelPolicy

ENTRY = ModelPolicy(
    name="qwen3:32b",
    status="beta",
    backend="llamacpp",
    context=32768,
    kv_cache="q8_0",
    flash_attention=True,
    gpu_mib=23740,
)


def _volume(root: Path, model_dir: str = "library/qwen3", tag: str = "32b") -> Path:
    manifest = root / "manifests" / "registry.ollama.ai" / model_dir / tag
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "layers": [
                    {"mediaType": "application/vnd.ollama.image.template", "digest": "sha256:t"},
                    {"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:abc"},
                ]
            }
        )
    )
    blobs = root / "blobs"
    blobs.mkdir()
    (blobs / "sha256-abc").write_bytes(b"gguf")
    return root


class BlobTests(unittest.TestCase):
    def test_finds_the_model_layer_through_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _volume(Path(tmp))
            self.assertEqual(
                serve.blob_for("qwen3:32b", root), (root / "blobs/sha256-abc").resolve()
            )

    def test_an_unpulled_model_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(serve.ServeError):
            serve.blob_for("nothing:1b", Path(tmp))

    def test_missing_weights_are_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _volume(Path(tmp))
            (root / "blobs/sha256-abc").unlink()
            with self.assertRaises(serve.ServeError):
                serve.blob_for("qwen3:32b", root)


class CommandTests(unittest.TestCase):
    def test_podman_argv_carries_the_entry_settings(self):
        argv = serve.podman_argv("qwen3:32b", ENTRY, Path("/b/sha256-abc"), 8081, gpu=[])
        text = " ".join(argv)
        self.assertIn("-c 32768", text)
        self.assertIn("-ctk q8_0 -ctv q8_0", text)
        self.assertIn("-fa on", text)
        self.assertIn("127.0.0.1:8081:8080", text)
        self.assertIn("--alias qwen3:32b", text)
        self.assertIn("/b/sha256-abc:/models/sha256-abc:ro", text)

    def test_speculative_type_is_passed_only_when_set(self):
        plain = serve.podman_argv("qwen3:32b", ENTRY, Path("/b/x"), 8081, gpu=[])
        self.assertNotIn("--spec-type", plain)
        ngram = ModelPolicy(name="m", backend="llamacpp", context=4096, speculative="ngram-mod")
        argv = serve.podman_argv("m", ngram, Path("/b/x"), 8081, gpu=[])
        self.assertEqual(argv[argv.index("--spec-type") + 1], "ngram-mod")

    def test_draft_model_adds_mount_and_speculative_flags(self):
        entry = ModelPolicy(
            name="m", backend="llamacpp", context=4096, draft="qwen3:0.6b-q8_0", draft_tokens=6
        )
        argv = serve.podman_argv("m", entry, Path("/b/x"), 8081, gpu=[], draft=Path("/g/d.gguf"))
        text = " ".join(argv)
        self.assertIn("/g/d.gguf:/models/d.gguf:ro", text)
        self.assertIn("-md /models/d.gguf -ngld 99 --spec-type draft-simple", text)
        self.assertIn("--spec-draft-n-max 6 --spec-draft-n-min 1", text)

    def test_missing_draft_file_names_the_fix(self):
        entry = ModelPolicy(name="m", backend="llamacpp", context=4096, draft="nope")
        with self.assertRaises(serve.ServeError):
            serve.draft_for(entry)
        self.assertIsNone(serve.draft_for(ModelPolicy(name="m")))

    def test_flash_attention_off_and_no_context(self):
        off = ModelPolicy(name="m", backend="llamacpp", context=4096, flash_attention=False)
        self.assertIn("off", serve.podman_argv("m", off, Path("/b/x"), 8081, gpu=[]))
        with self.assertRaises(serve.ServeError):
            serve.podman_argv("m", ModelPolicy(name="m", backend="llamacpp"), Path("/b/x"), 1)

    def test_port_comes_from_the_backend_url(self):
        self.assertEqual(serve.server_port("http://localhost:9000"), 9000)
        self.assertEqual(serve.server_port("http://localhost"), 8081)

    def test_ollama_models_need_nothing_started(self):
        entry = ModelPolicy(name="qwen3:14b", backend="ollama", status="default")
        self.assertIsNone(serve.plan("qwen3:14b", entry, "http://localhost:8081"))

    def test_unlisted_and_retired_models_are_refused(self):
        with self.assertRaises(serve.ServeError):
            serve.plan("x", None, "http://localhost:8081")
        retired = ModelPolicy(name="x", backend="llamacpp", status="retired")
        with self.assertRaises(serve.ServeError):
            serve.plan("x", retired, "http://localhost:8081")


class LeaseTests(unittest.TestCase):
    def test_wraps_in_a_sized_lease_that_owns_the_server_process(self):
        cmd = serve.lease_command(
            "m", ["podman", "run"], 9000, total_mib=24576, which=lambda _: "/bin/ecu", environ={}
        )
        self.assertEqual(cmd[:4], ["/bin/ecu", "run", "--gpu-mib", str(9000 + serve.HEADROOM_MIB)])
        self.assertIn("--own-gpu-process", cmd)
        self.assertEqual(cmd[-2:], ["podman", "run"])

    def test_a_model_that_leaves_no_headroom_takes_the_whole_gpu(self):
        self.assertEqual(serve.lease_size(23740, 24576), ["--gpu", "exclusive"])
        self.assertEqual(serve.lease_size(9000, None), ["--gpu", "exclusive"])

    def test_skipped_without_ecu_or_inside_a_lease_or_when_disabled(self):
        self.assertIsNone(serve.lease_command("m", ["x"], 1, which=lambda _: None, environ={}))
        for env in ({serve.LEASE_ENV: "1"}, {"CREW_CHIEF_NO_LEASE": "1"}):
            self.assertIsNone(
                serve.lease_command("m", ["x"], 1, which=lambda _: "/bin/ecu", environ=env)
            )


class ParserTests(unittest.TestCase):
    def test_serve_parses(self):
        args = build_parser().parse_args(["serve", "qwen3:32b", "--dry-run"])
        self.assertEqual(args.serve_models, ["qwen3:32b"])
        self.assertTrue(args.dry_run)

    def test_swap_parses_several_models(self):
        args = build_parser().parse_args(["serve", "--swap", "a", "b", "--ttl", "60"])
        self.assertTrue(args.swap)
        self.assertEqual((args.serve_models, args.ttl, args.port), (["a", "b"], 60, 8085))


class SwapTests(unittest.TestCase):
    def test_config_gives_each_model_its_policy_flags(self):
        small = ModelPolicy(name="small", backend="llamacpp", context=4096, speculative="ngram-mod")
        models = [
            ("qwen3:32b", ENTRY, Path("/b/sha256-abc"), None),
            ("small", small, Path("/b/sha256-d"), None),
        ]
        config = serve.swap_config(models, ttl=60)
        self.assertIn('"qwen3:32b":', config)
        self.assertIn("ttl: 60", config)
        self.assertIn("--port ${PORT}", config)
        self.assertIn("-m /models/sha256-abc --alias qwen3:32b", config)
        self.assertIn("-ctk q8_0 -ctv q8_0", config)
        self.assertIn("--spec-type ngram-mod", config)
        self.assertEqual(config.count("--spec-type"), 1)

    def test_config_needs_a_context(self):
        bare = ModelPolicy(name="m", backend="llamacpp")
        with self.assertRaises(serve.ServeError):
            serve.swap_config([("m", bare, Path("/b/x"), None)])

    def test_argv_mounts_every_blob_and_the_config(self):
        models = [
            ("a", ENTRY, Path("/b/sha256-1"), None),
            ("b", ENTRY, Path("/b/sha256-2"), Path("/g/d.gguf")),
        ]
        text = " ".join(serve.swap_argv(models, Path("/t/c.yaml"), 8085, gpu=[]))
        self.assertIn("/b/sha256-1:/models/sha256-1:ro", text)
        self.assertIn("/b/sha256-2:/models/sha256-2:ro", text)
        self.assertIn("/g/d.gguf:/models/d.gguf:ro", text)
        self.assertIn("/t/c.yaml:/config/config.yaml:ro", text)
        self.assertIn("127.0.0.1:8085:8080", text)
        self.assertIn("-config /config/config.yaml", text)

    def test_plan_swap_rejects_unknown_and_retired(self):
        class Policy:
            def get(self, name):
                return {"gone": ModelPolicy(name="gone", status="retired")}.get(name)

        for name in ("missing", "gone"):
            with self.subTest(name=name), self.assertRaises(serve.ServeError):
                serve.plan_swap([name], Policy(), run=lambda *a, **k: None)


if __name__ == "__main__":
    unittest.main()
