"""Every key of the listener config: what it accepts, and what it refuses by name.

A listener runs unattended and sends messages, so a config that is read wrongly (a
quoted number, a misspelt section, a table where a list belongs) must fail at start-up
with a message that names the key, not be coerced into something plausible.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crew_chief.config_loader import ConfigError, ListenerConfig, load

# (section, key, valid TOML literal, value expected back, invalid TOML literal)
STR, INT, BOOL = ('"text"', "text", "5"), ("7", 7, '"7"'), ("true", True, '"yes"')
STRS = ('["a", "b"]', ["a", "b"], '"a"')

KEYS = [
    ("listener", "poll_interval_seconds", *INT),
    ("listener", "max_replies_per_cycle", *INT),
    ("llm", "model", *STR),
    ("llm", "natural_language", *BOOL),
    ("llm", "decision_gate", *BOOL),
    ("llm", "decision_gate_threshold", "0.5", 0.5, '"high"'),
    ("llm", "base_url", *STR),
    ("llm", "timeout_seconds", *INT),
    ("llm", "provider", *STR),
    ("llm", "fallback_chain", *STRS),
    ("llm", "ollama_model_chain", *STRS),
    ("llm", "api_key_env", *STR),
    ("llm", "anthropic_api_key_auto_pass_entry", *STR),
    ("llm", "auto_pass_env_file", *STR),
    ("llm", "max_tokens", *INT),
    ("llm", "claude_cli_model", *STR),
    ("llm", "claude_cli_allowed_tools", *STR),
    ("llm", "codex_cli_model", *STR),
    ("llm", "codex_cli_sandbox", *STR),
    ("llm", "openai_api_key_env", *STR),
    ("llm", "openai_api_key_auto_pass_entry", *STR),
    ("llm", "openai_model", *STR),
    ("agent", "enabled", *BOOL),
    ("agent", "max_iterations", *INT),
    ("agent", "system_prompt", *STR),
    ("agent", "tools", *STRS),
    ("agent", "allowed_paths", *STRS),
    ("agent", "provider", *STR),
    ("agent", "fallback_chain", *STRS),
    ("agent", "confidence_threshold", "0.25", 0.25, '"low"'),
    ("agent", "timeout_seconds", *INT),
    ("signal", "enabled", *BOOL),
    ("signal", "shock_relay_dir", *STR),
    ("signal", "config_path", *STR),
    ("signal", "trusted_senders", *STRS),
    ("signal", "reply_to", *STR),
    ("gmail", "enabled", *BOOL),
    ("gmail", "shock_relay_dir", *STR),
    ("gmail", "config_path", *STR),
    ("gmail", "trusted_senders", *STRS),
    ("gmail", "reply_to", *STR),
    ("gmail", "since_days", *INT),
    ("gmail", "limit", *INT),
    ("gmail", "subject_exclude_patterns", *STRS),
    ("gmail", "service_reply_subject_prefixes", *STRS),
    ("dispatch", "timeout_seconds", *INT),
    ("dispatch", "output_max_bytes", *INT),
    ("dispatch", "allowed_commands", *STRS),
]


def _load(body: str) -> ListenerConfig:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "listener.toml"
        path.write_text(body, encoding="utf-8")
        return load(path)


def _attr(cfg: ListenerConfig, section: str, key: str):
    return getattr(cfg if section == "listener" else getattr(cfg, section), key)


class EveryKey(unittest.TestCase):
    def test_each_key_is_read_into_the_field_of_the_same_name(self) -> None:
        for section, key, good, expected, _ in KEYS:
            with self.subTest(key=f"{section}.{key}"):
                cfg = _load(f"[{section}]\n{key} = {good}\n")
                self.assertEqual(_attr(cfg, section, key), expected)

    def test_a_key_set_in_one_section_does_not_leak_into_another(self) -> None:
        cfg = _load('[signal]\nreply_to = "sig"\n')
        self.assertEqual(cfg.signal.reply_to, "sig")
        self.assertNotEqual(cfg.gmail.reply_to, "sig")

    def test_each_key_refuses_a_value_of_the_wrong_type_and_names_itself(self) -> None:
        for section, key, _, _, bad in KEYS:
            with self.subTest(key=f"{section}.{key}"), self.assertRaises(ConfigError) as raised:
                _load(f"[{section}]\n{key} = {bad}\n")
            self.assertIn(f"{section}.{key}", str(raised.exception))

    def test_the_empty_file_is_the_defaults(self) -> None:
        cfg = _load("")
        self.assertEqual(cfg.poll_interval_seconds, 30)
        self.assertEqual(cfg.max_replies_per_cycle, 0)
        self.assertEqual(cfg, ListenerConfig())


class Numbers(unittest.TestCase):
    def test_booleans_are_not_numbers(self) -> None:
        # bool is an int subclass: `true` must not become a poll interval of 1
        for section, key in (
            ("listener", "poll_interval_seconds"),
            ("listener", "max_replies_per_cycle"),
            ("llm", "max_tokens"),
            ("dispatch", "timeout_seconds"),
            ("llm", "decision_gate_threshold"),
            ("agent", "confidence_threshold"),
        ):
            with self.subTest(key=f"{section}.{key}"), self.assertRaises(ConfigError):
                _load(f"[{section}]\n{key} = true\n")

    def test_a_whole_number_is_accepted_where_a_float_is_expected(self) -> None:
        cfg = _load("[agent]\nconfidence_threshold = 1\n")
        self.assertEqual(cfg.agent.confidence_threshold, 1.0)
        self.assertIsInstance(cfg.agent.confidence_threshold, float)

    def test_an_integer_key_refuses_a_fraction(self) -> None:
        with self.assertRaises(ConfigError):
            _load("[listener]\npoll_interval_seconds = 2.5\n")

    def test_the_decision_gate_threshold_must_be_above_zero_and_at_most_one(self) -> None:
        for bad in ("0", "0.0", "-0.1", "1.01", "2"):
            with self.subTest(threshold=bad), self.assertRaises(ConfigError) as raised:
                _load(f"[llm]\ndecision_gate_threshold = {bad}\n")
            self.assertIn("(0, 1]", str(raised.exception))
        for good in ("0.01", "0.5", "1", "1.0"):
            with self.subTest(threshold=good):
                self.assertGreater(
                    _load(f"[llm]\ndecision_gate_threshold = {good}\n").llm.decision_gate_threshold,
                    0,
                )


class ListsAndTables(unittest.TestCase):
    def test_a_list_of_strings_must_hold_only_strings(self) -> None:
        for bad in ('["a", 1]', "[1, 2]", '[["a"]]', '"a,b"', "{a = 1}"):
            with self.subTest(value=bad), self.assertRaises(ConfigError):
                _load(f"[gmail]\ntrusted_senders = {bad}\n")

    def test_an_empty_list_is_a_valid_empty_allowlist(self) -> None:
        self.assertEqual(_load("[signal]\ntrusted_senders = []\n").signal.trusted_senders, [])

    def test_task_chains_map_each_task_to_a_list_of_models(self) -> None:
        cfg = _load('[llm.task_chains]\nroute = ["a", "b"]\nsummarise = ["c"]\n')
        self.assertEqual(cfg.llm.task_chains, {"route": ["a", "b"], "summarise": ["c"]})

    def test_task_chains_refuse_a_non_table_and_name_the_bad_task(self) -> None:
        with self.assertRaises(ConfigError) as raised:
            _load('[llm]\ntask_chains = ["a"]\n')
        self.assertIn("llm.task_chains", str(raised.exception))
        with self.assertRaises(ConfigError) as raised:
            _load('[llm.task_chains]\nroute = "a"\n')
        self.assertIn("llm.task_chains.route", str(raised.exception))

    def test_a_section_must_be_a_table(self) -> None:
        # `llm = 5` used to escape as a TypeError; `listener = "x"` was silently ignored
        for section in ("listener", "llm", "agent", "signal", "gmail", "dispatch"):
            for bad in ("5", '"x"', "[1]", "true"):
                with (
                    self.subTest(section=section, value=bad),
                    self.assertRaises(ConfigError) as raised,
                ):
                    _load(f"{section} = {bad}\n")
                self.assertIn(f"[{section}]", str(raised.exception))

    def test_a_missing_section_is_simply_the_defaults(self) -> None:
        cfg = _load("[gmail]\nlimit = 3\n")
        self.assertEqual(cfg.signal, ListenerConfig().signal)


class Files(unittest.TestCase):
    def test_a_missing_file_is_a_config_error_naming_the_path(self) -> None:
        with self.assertRaises(ConfigError) as raised:
            load("/nonexistent/listener.toml")
        self.assertIn("/nonexistent/listener.toml", str(raised.exception))
        self.assertIn("not found", str(raised.exception))

    def test_malformed_toml_is_a_config_error(self) -> None:
        with self.assertRaises(ConfigError) as raised:
            _load("[llm\nmodel =\n")
        self.assertIn("Cannot parse", str(raised.exception))

    def test_a_path_can_be_text_or_a_path_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "c.toml"
            path.write_text("[listener]\npoll_interval_seconds = 5\n", encoding="utf-8")
            self.assertEqual(load(str(path)).poll_interval_seconds, 5)
            self.assertEqual(load(path).poll_interval_seconds, 5)

    def test_a_directory_is_not_a_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ConfigError):
            load(directory)


if __name__ == "__main__":
    unittest.main()
