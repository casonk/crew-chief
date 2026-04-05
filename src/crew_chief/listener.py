"""crew_chief.listener — poll Signal and Gmail for commands; dispatch and reply.

Architecture
------------
The listener runs a configurable poll loop:

1. **Signal** — calls ``signal-cli --output=json -a <account> receive
   --timeout <N>`` directly, using the account read from the shock-relay
   ``config.local.yaml``.  Each JSON-line envelope is parsed; only
   ``dataMessage`` envelopes from trusted senders are processed.

2. **Gmail** — invokes ``shock-relay/services/gmail-imap/check_inbox.py
   --unseen --limit N --since-days N`` as a subprocess and parses the JSON
   response.  Only messages from trusted senders are processed.

3. **LLM routing** — when ``llm.natural_language = true``, the message text
   is passed to the local Ollama service with a system prompt that asks it to
   extract a shell command from the configured allowlist.  When
   ``natural_language = false`` (or when the message starts with ``!``), the
   text after ``!`` is used verbatim as the command.

4. **Dispatch** — the extracted command is validated against the fnmatch
   allowlist in :class:`~crew_chief.dispatcher.Dispatcher` and executed if
   permitted.  No shell expansion is used.

5. **Reply** — the command output is sent back to the original sender via the
   appropriate shock-relay send script (``send_message.py`` for Signal,
   ``send_email.py`` for Gmail).

Security model
--------------
- Messages from unknown senders are silently ignored before any LLM or
  dispatch processing.
- Commands must match the configured fnmatch allowlist regardless of whether
  they were produced by the LLM or typed directly.
- ``shell=False`` throughout — shell operators in message text cannot be
  interpreted by the OS.
- The LLM prompt instructs the model to output *only* a JSON object.  The
  response is parsed as JSON; free-form text is treated as a null command.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from crew_chief.client import CrewChiefClient
from crew_chief.config_loader import GmailConfig, ListenerConfig, SignalConfig
from crew_chief.dispatcher import Dispatcher, DispatchResult

log = logging.getLogger(__name__)


def _signal_tmpdir() -> str:
    """Return a writable tmpdir for signal-cli's native library extraction.

    signal-cli (GraalVM native image) extracts libsignal to java.io.tmpdir at
    startup.  /tmp may be restricted in a user-service context (e.g. SELinux);
    XDG_RUNTIME_DIR (/run/user/<uid>) is always writable.
    """
    return os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"


def _signal_env() -> dict[str, str]:
    """Return os.environ extended with signal-cli tmpdir overrides.

    Sets both TMPDIR (so any subprocess that shells out to signal-cli inherits
    it) and JAVA_TOOL_OPTIONS (belt-and-suspenders for non-native JVM callers).
    The -Djava.io.tmpdir flag must be passed directly on the signal-cli command
    line for GraalVM native images — JAVA_TOOL_OPTIONS is silently ignored by
    them — but TMPDIR is read by the runtime and is the reliable path.
    """
    tmpdir = _signal_tmpdir()
    env = os.environ.copy()
    env["TMPDIR"] = tmpdir
    env["JAVA_TOOL_OPTIONS"] = f"-Djava.io.tmpdir={tmpdir}"
    return env


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are a command-routing assistant embedded in a secure local automation system.

Your sole job is to inspect a user message and decide whether it maps to one \
of the allowed shell commands listed below.

Allowed command patterns (fnmatch-style globs):
{allowlist}

Rules:
- If the message clearly maps to an allowed command, respond with ONLY a JSON \
object on a single line, no markdown:
  {{"command": "<exact shell command to run>"}}
- If the message does not map to any allowed command, is ambiguous, or could be \
dangerous, respond with ONLY:
  {{"command": null, "reason": "<brief one-sentence explanation>"}}
- Never add explanation text outside the JSON object.
- Never include shell operators (&&, ||, ;, |, >, <, backticks, $()) unless \
the matching pattern explicitly contains them.
- Prefer the simplest valid form of the command (e.g. "df -h" not "df -ah --si").
"""

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class IncomingMessage:
    """A normalised inbound message from any supported channel."""

    channel: str  # "signal" or "gmail"
    sender: str  # phone number or email address
    text: str  # plain-text body
    subject: str = ""  # subject line (Gmail only)
    raw: dict = None  # original parsed object

    def __post_init__(self) -> None:
        if self.raw is None:
            self.raw = {}


# ---------------------------------------------------------------------------
# Signal helpers
# ---------------------------------------------------------------------------


def _parse_signal_account(config_path: str) -> str:
    """Extract the ``signal_cli.account`` field from a shock-relay config file."""
    text = Path(config_path).read_text(encoding="utf-8")
    in_block = False
    base_indent: int | None = None
    for line in text.splitlines():
        if not in_block:
            if re.match(r"^\s*signal_cli:\s*$", line):
                in_block = True
                base_indent = len(line) - len(line.lstrip())
            continue
        if line.strip():
            indent = len(line) - len(line.lstrip())
            if base_indent is not None and indent <= base_indent:
                break
        m = re.match(r"^\s*account:\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s#]+))", line)
        if m:
            return next(v for v in m.groups() if v is not None)
    return ""


def _parse_signal_json_lines(raw_output: str) -> list[dict[str, Any]]:
    """Parse signal-cli JSON-line output into a list of envelope dicts."""
    envelopes = []
    for line in raw_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        envelopes.append(obj)
    return envelopes


def poll_signal(cfg: SignalConfig) -> list[IncomingMessage]:
    """Receive pending Signal messages and return those from trusted senders.

    Calls ``signal-cli --output=json -a <account> receive --timeout 5``
    directly.  Returns an empty list if Signal is disabled, mis-configured,
    or the receive command fails.
    """
    if not cfg.enabled:
        return []
    if not cfg.config_path or not cfg.shock_relay_dir:
        log.warning("Signal enabled but shock_relay_dir / config_path not set — skipping.")
        return []

    try:
        account = _parse_signal_account(cfg.config_path)
    except OSError as exc:
        log.error("Cannot read Signal config %s: %s", cfg.config_path, exc)
        return []

    if not account:
        log.error("No signal_cli.account found in %s", cfg.config_path)
        return []

    tmpdir = _signal_tmpdir()
    cmd = [
        "signal-cli",
        f"-Djava.io.tmpdir={tmpdir}",  # GraalVM native images require -D on the CLI
        "--output=json",
        "-a",
        account,
        "receive",
        "--timeout",
        "5",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=_signal_env())
    except FileNotFoundError:
        log.error("signal-cli not found — is it installed and on PATH?")
        return []
    except subprocess.TimeoutExpired:
        log.warning("signal-cli receive timed out unexpectedly.")
        return []

    if result.returncode != 0:
        log.error(
            "signal-cli receive failed (rc=%d): %s", result.returncode, result.stderr.strip()[:300]
        )
        return []
    log.info("signal-cli rc=0 stdout=%r stderr=%r", result.stdout[:500], result.stderr[:200])

    messages: list[IncomingMessage] = []
    for envelope in _parse_signal_json_lines(result.stdout):
        env = envelope.get("envelope", {})
        source = env.get("sourceNumber") or env.get("source", "")

        # Regular incoming message.
        dm = env.get("dataMessage")

        # Linked-device sync: note-to-self messages sent from the primary device
        # arrive as syncMessage.sentMessage rather than dataMessage.
        if not dm:
            sent = env.get("syncMessage", {}).get("sentMessage", {})
            if sent:
                dm = sent

        if not dm:
            continue  # receipt, typing indicator, etc.
        text = dm.get("message", "")
        if not text:
            continue
        if source not in cfg.trusted_senders:
            log.debug("Signal: ignoring message from untrusted sender %s", source)
            continue
        messages.append(IncomingMessage(channel="signal", sender=source, text=text, raw=envelope))
    return messages


def reply_signal(cfg: SignalConfig, recipient: str, text: str) -> None:
    """Send *text* back to *recipient* via the shock-relay send_message.py script."""
    send_script = Path(cfg.shock_relay_dir) / "send_message.py"
    cmd = [
        sys.executable,
        str(send_script),
        "--config",
        cfg.config_path,
        recipient,
        text,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=_signal_env())
        if result.returncode != 0:
            log.error("Signal reply failed (rc=%d): %s", result.returncode, result.stderr.strip())
    except subprocess.TimeoutExpired:
        log.error("Signal reply timed out sending to %s", recipient)
    except FileNotFoundError:
        log.error("send_message.py not found at %s", send_script)


# ---------------------------------------------------------------------------
# Gmail helpers
# ---------------------------------------------------------------------------


def _extract_email_address(raw_from: str) -> str:
    """Extract the bare email address from a 'Name <addr>' or plain 'addr' string."""
    _, addr = parseaddr(raw_from)
    return addr.lower().strip()


def poll_gmail(cfg: GmailConfig) -> list[IncomingMessage]:
    """Fetch unseen Gmail messages and return those from trusted senders.

    Calls ``check_inbox.py --unseen --limit N --since-days N`` as a subprocess
    and parses the JSON output.
    """
    if not cfg.enabled:
        return []
    if not cfg.config_path or not cfg.shock_relay_dir:
        log.warning("Gmail enabled but shock_relay_dir / config_path not set — skipping.")
        return []

    check_script = Path(cfg.shock_relay_dir) / "check_inbox.py"
    cmd = [
        sys.executable,
        str(check_script),
        "--config",
        cfg.config_path,
        "--unseen",
        "--limit",
        str(cfg.limit),
        "--since-days",
        str(cfg.since_days),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        log.error("check_inbox.py not found at %s", check_script)
        return []
    except subprocess.TimeoutExpired:
        log.error("Gmail check_inbox timed out.")
        return []

    if result.returncode != 0:
        log.error("check_inbox.py failed (rc=%d): %s", result.returncode, result.stderr.strip())
        return []

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        log.error("Cannot parse check_inbox.py output: %s", exc)
        return []

    trusted_lower = {addr.lower() for addr in cfg.trusted_senders}
    messages: list[IncomingMessage] = []
    for msg in payload.get("messages", []):
        sender_raw = msg.get("from", "")
        sender = _extract_email_address(sender_raw)
        if sender not in trusted_lower:
            log.debug("Gmail: ignoring message from untrusted sender %s", sender)
            continue
        subject = msg.get("subject", "")
        body = msg.get("snippet", msg.get("body", ""))
        if not body:
            continue
        messages.append(
            IncomingMessage(
                channel="gmail",
                sender=sender,
                text=body,
                subject=subject,
                raw=msg,
            )
        )
    return messages


def reply_gmail(cfg: GmailConfig, recipient: str, subject: str, body: str) -> None:
    """Send *body* to *recipient* via the shock-relay send_email.py script."""
    send_script = Path(cfg.shock_relay_dir) / "send_email.py"
    reply_subject = f"Re: {subject}" if subject else "crew-chief reply"
    cmd = [
        sys.executable,
        str(send_script),
        "--config",
        cfg.config_path,
        recipient,
        reply_subject,
        body,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            log.error("Gmail reply failed (rc=%d): %s", result.returncode, result.stderr.strip())
    except subprocess.TimeoutExpired:
        log.error("Gmail reply timed out sending to %s", recipient)
    except FileNotFoundError:
        log.error("send_email.py not found at %s", send_script)


# ---------------------------------------------------------------------------
# LLM command extraction
# ---------------------------------------------------------------------------

# Prefix that triggers direct-command mode without LLM involvement.
DIRECT_PREFIX = "!"


def _build_system_prompt(allowed_commands: list[str]) -> str:
    allowlist_str = "\n".join(f"  {p}" for p in allowed_commands)
    return _SYSTEM_PROMPT_TEMPLATE.format(allowlist=allowlist_str)


def extract_command_via_llm(
    text: str,
    client: CrewChiefClient,
    allowed_commands: list[str],
) -> str | None:
    """Ask the LLM to interpret *text* as a shell command from the allowlist.

    Returns the command string on success, or ``None`` if the LLM indicates
    the message does not map to an allowed command or the response cannot be
    parsed.
    """
    system_prompt = _build_system_prompt(allowed_commands)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text},
    ]
    try:
        raw = client.chat(messages)
    except Exception as exc:
        log.error("LLM request failed: %s", exc)
        return None

    # Extract the first JSON object from the response — the model may wrap it
    # in extra whitespace but should not add other text.
    raw = raw.strip()
    json_start = raw.find("{")
    json_end = raw.rfind("}") + 1
    if json_start == -1 or json_end <= json_start:
        log.warning("LLM response is not JSON: %r", raw[:200])
        return None

    try:
        parsed = json.loads(raw[json_start:json_end])
    except json.JSONDecodeError:
        log.warning("LLM returned invalid JSON: %r", raw[:200])
        return None

    command = parsed.get("command")
    if not command:
        reason = parsed.get("reason", "no matching command")
        log.info("LLM declined to map message to a command: %s", reason)
        return None

    return str(command).strip()


def resolve_command(
    text: str,
    cfg: ListenerConfig,
    llm_client: CrewChiefClient,
) -> str | None:
    """Determine the shell command to run for an incoming message.

    Direct-command mode: text starting with ``!`` → strip the prefix and use
    the remainder verbatim (still subject to allowlist enforcement in the
    dispatcher).

    Natural-language mode (``cfg.llm.natural_language = True``): route through
    the LLM to extract the intended command.

    Returns ``None`` when no actionable command can be extracted.
    """
    stripped = text.strip()

    if stripped.startswith(DIRECT_PREFIX):
        command = stripped[len(DIRECT_PREFIX) :].strip()
        return command if command else None

    if cfg.llm.natural_language:
        return extract_command_via_llm(
            stripped,
            llm_client,
            cfg.dispatch.allowed_commands,
        )

    # natural_language=False and no "!" prefix — ignore the message.
    log.debug("Ignoring message (natural_language=False, no ! prefix): %r", stripped[:80])
    return None


# ---------------------------------------------------------------------------
# Main listener loop
# ---------------------------------------------------------------------------


def _process_message(
    msg: IncomingMessage,
    cfg: ListenerConfig,
    llm_client: CrewChiefClient,
    dispatcher: Dispatcher,
) -> None:
    """Interpret, dispatch, and reply to a single incoming message."""
    log.info("[%s] Message from %s: %r", msg.channel, msg.sender, msg.text[:80])

    command = resolve_command(msg.text, cfg, llm_client)
    if command is None:
        log.info("[%s] No actionable command extracted from message.", msg.channel)
        return

    log.info("[%s] Dispatching: %r", msg.channel, command)
    result: DispatchResult = dispatcher.run(command)

    reply_text = result.reply_text()
    log.info("[%s] Reply (%d chars): %r", msg.channel, len(reply_text), reply_text[:80])

    if msg.channel == "signal":
        reply_signal(cfg.signal, msg.sender, reply_text)
    elif msg.channel == "gmail":
        reply_gmail(cfg.gmail, cfg.gmail.reply_to or msg.sender, msg.subject, reply_text)


def run(cfg: ListenerConfig, *, once: bool = False) -> None:
    """Start the listener polling loop.

    Parameters
    ----------
    cfg:
        Loaded :class:`~crew_chief.config_loader.ListenerConfig`.
    once:
        If ``True``, run a single poll cycle and return.  Useful for testing
        and one-shot invocations.
    """
    llm_client = CrewChiefClient(
        base_url=cfg.llm.base_url,
        model=cfg.llm.model,
        timeout=cfg.llm.timeout_seconds,
    )
    dispatcher = Dispatcher(
        allowed_commands=cfg.dispatch.allowed_commands,
        timeout_seconds=cfg.dispatch.timeout_seconds,
        max_output_bytes=cfg.dispatch.output_max_bytes,
    )

    log.info(
        "crew-chief listener started (Signal=%s, Gmail=%s, interval=%ds).",
        cfg.signal.enabled,
        cfg.gmail.enabled,
        cfg.poll_interval_seconds,
    )

    while True:
        cycle_start = time.monotonic()

        for msg in poll_signal(cfg.signal):
            _process_message(msg, cfg, llm_client, dispatcher)

        for msg in poll_gmail(cfg.gmail):
            _process_message(msg, cfg, llm_client, dispatcher)

        if once:
            break

        elapsed = time.monotonic() - cycle_start
        sleep_for = max(0.0, cfg.poll_interval_seconds - elapsed)
        if sleep_for > 0:
            time.sleep(sleep_for)
