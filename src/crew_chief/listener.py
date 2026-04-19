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

from crew_chief.agent import Agent, AgentCascade
from crew_chief.client import CrewChiefClient
from crew_chief.config_loader import GmailConfig, ListenerConfig, SignalConfig
from crew_chief.dispatcher import Dispatcher, DispatchResult
from crew_chief.providers import build_provider, get_provider
from crew_chief.tools import build_tools

log = logging.getLogger(__name__)

_SIGNAL_PROTOCOL_KEYS = frozenset({"cc-service", "cc-intent", "cc-target"})
_SIGNAL_PROTOCOL_LINE_RE = re.compile(r"\s*(cc-[a-z0-9-]+)\s*:\s*(.+?)\s*$", re.IGNORECASE)
_SIGNAL_SERVICE_KEY = "cc-service"
_SIGNAL_INTENT_KEY = "cc-intent"
_SIGNAL_TARGET_KEY = "cc-target"
_SIGNAL_REQUEST_INTENT = "request"
_SIGNAL_RESPONSE_INTENT = "response"
_CREW_CHIEF_TARGET = "crew-chief"
_CREW_CHIEF_TEXT_PREFIX = "[crew-chief]"
_SIGNAL_REQUEST_PREFIX_RE = re.compile(r"^(?:@\s*)?(?:crew(?:[-\s]+)chief|chief)\b", re.IGNORECASE)


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

    own_sender = (cfg.reply_to or account).strip()
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
        metadata, stripped_text = _split_signal_metadata_block(text)
        intent = _signal_metadata_value(metadata, _SIGNAL_INTENT_KEY)
        target = _signal_metadata_value(metadata, _SIGNAL_TARGET_KEY)
        service_name = _signal_metadata_value(metadata, _SIGNAL_SERVICE_KEY)
        if metadata and not _is_signal_request_metadata(metadata):
            log.info(
                "Signal: skipping message from %s with non-request metadata "
                "(service=%s, intent=%r, target=%r).",
                source,
                service_name or "unknown",
                intent or None,
                target or None,
            )
            continue
        explicit_request = _is_explicit_signal_request(stripped_text, metadata)
        if own_sender and source == own_sender and not explicit_request:
            log.warning(
                "Signal: dropping same-sender message from %s without crew-chief request intent.",
                source,
            )
            continue
        if not stripped_text:
            continue
        if source not in cfg.trusted_senders:
            log.debug("Signal: ignoring message from untrusted sender %s", source)
            continue
        messages.append(
            IncomingMessage(channel="signal", sender=source, text=stripped_text, raw=envelope)
        )
    return messages


def reply_signal(cfg: SignalConfig, recipient: str, text: str) -> None:
    """Send *text* back to *recipient* via the shock-relay send_message.py script."""
    send_script = Path(cfg.shock_relay_dir) / "send_message.py"
    cmd = [
        sys.executable,
        str(send_script),
        "--meta",
        "cc-service: crew-chief",
        "--meta",
        f"cc-intent: {_SIGNAL_RESPONSE_INTENT}",
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
    own_address = (cfg.reply_to or "").lower().strip()
    messages: list[IncomingMessage] = []
    for msg in payload.get("messages", []):
        sender_raw = msg.get("from", "")
        sender = _extract_email_address(sender_raw)
        if sender not in trusted_lower:
            log.debug("Gmail: ignoring message from untrusted sender %s", sender)
            continue

        # Loop guard 2: honour standard email auto-reply headers.
        if _is_auto_reply(msg):
            log.warning(
                "Gmail: dropping auto-reply from %s (subject=%r) — loop guard.",
                sender,
                msg.get("subject", ""),
            )
            continue

        subject = msg.get("subject", "")

        # Subject exclusion filter: drop emails from pipelines that share the inbox.
        if _subject_is_excluded(subject, cfg.subject_exclude_patterns):
            log.info(
                "Gmail: skipping email from %s with excluded subject %r.",
                sender,
                subject,
            )
            continue

        body = _gmail_body_text(msg)
        if not body:
            continue

        intent = _gmail_intent(msg)
        service_name = _gmail_service_name(msg)
        if service_name and intent != _CREW_CHIEF_REQUEST_INTENT:
            log.info(
                "Gmail: skipping email from %s for service=%s without request intent (intent=%r).",
                sender,
                service_name,
                intent or None,
            )
            continue
        if intent and intent != _CREW_CHIEF_REQUEST_INTENT:
            log.info(
                "Gmail: skipping email from %s with non-request intent %r (service=%s).",
                sender,
                intent,
                service_name or "unknown",
            )
            continue

        explicit_request = _is_explicit_crew_chief_request(msg, subject, body)

        # Loop guard 1: same-address Gmail is ambiguous unless the message
        # explicitly declares itself as a request to crew-chief.
        if own_address and sender == own_address and not explicit_request:
            log.warning(
                "Gmail: dropping same-address message from %s without crew-chief request intent.",
                sender,
            )
            continue

        # Loop guard 3: drop messages containing crew-chief's own reply marker.
        if any(_REPLY_LOOP_MARKER in candidate for candidate in _gmail_body_candidates(msg)):
            log.warning(
                "Gmail: dropping message from %s containing crew-chief marker — loop guard.",
                sender,
            )
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
    # Append the loop-prevention marker so any system that routes this reply
    # back to crew-chief's inbox will have it filtered out on ingest.
    stamped_body = f"{body}\n\n{_REPLY_LOOP_MARKER}"
    cmd = [
        sys.executable,
        str(send_script),
        "--header",
        "X-Portfolio-Service: crew-chief",
        "--header",
        f"X-Crew-Chief-Intent: {_CREW_CHIEF_RESPONSE_INTENT}",
        "--config",
        cfg.config_path,
        recipient,
        reply_subject,
        stamped_body,
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


def _split_signal_metadata_block(text: str) -> tuple[dict[str, str], str]:
    """Return a parsed leading Signal metadata block plus the stripped body."""
    if not text:
        return {}, text
    lines = text.splitlines()
    metadata: dict[str, str] = {}
    for index, line in enumerate(lines):
        if not line.strip():
            if metadata:
                body = "\n".join(lines[index + 1 :]).lstrip("\n")
                return metadata, body
            return {}, text
        match = _SIGNAL_PROTOCOL_LINE_RE.fullmatch(line)
        if not match:
            return {}, text
        key = match.group(1).lower()
        if key not in _SIGNAL_PROTOCOL_KEYS:
            return {}, text
        metadata[key] = match.group(2).strip()
    return {}, text


def _signal_metadata_value(metadata: dict[str, str], key: str) -> str:
    """Return a normalized Signal metadata value, if present."""
    return metadata.get(key, "").strip().lower()


def _is_signal_request_metadata(metadata: dict[str, str]) -> bool:
    """Return ``True`` when Signal metadata explicitly targets crew-chief."""
    intent = _signal_metadata_value(metadata, _SIGNAL_INTENT_KEY)
    if intent != _SIGNAL_REQUEST_INTENT:
        return False
    target = _signal_metadata_value(metadata, _SIGNAL_TARGET_KEY)
    return not target or target == _CREW_CHIEF_TARGET


def _is_explicit_signal_request(text: str, metadata: dict[str, str]) -> bool:
    """Return ``True`` when a Signal message unambiguously targets crew-chief."""
    if _is_signal_request_metadata(metadata):
        return True
    stripped = text.lstrip().lower()
    return (
        stripped.startswith(DIRECT_PREFIX)
        or stripped.startswith(_CREW_CHIEF_TEXT_PREFIX)
        or bool(_SIGNAL_REQUEST_PREFIX_RE.match(text.lstrip()))
    )


# ---------------------------------------------------------------------------
# Loop-prevention helpers
# ---------------------------------------------------------------------------

# Machine-readable marker appended to every outgoing Gmail reply.  Inbound
# messages that contain this token are treated as crew-chief's own replies and
# dropped before any processing occurs.
_REPLY_LOOP_MARKER = "<!-- crew-chief-id -->"

_PORTFOLIO_SERVICE_HEADER = "x-portfolio-service"
_CREW_CHIEF_INTENT_HEADER = "x-crew-chief-intent"
_CREW_CHIEF_REQUEST_INTENT = "request"
_CREW_CHIEF_RESPONSE_INTENT = "response"
_CREW_CHIEF_SUBJECT_PREFIX = _CREW_CHIEF_TEXT_PREFIX

# Subjects that identify user replies to portfolio service notifications.
# These are treated as explicit requests so the same-sender loop guard passes them.
_SERVICE_REPLY_SUBJECT_PREFIXES: tuple[str, ...] = ("re: [intake]",)

# Header names whose *presence alone* (regardless of value) signals an
# automated reply.  Checked case-insensitively.
_AUTO_REPLY_HEADER_NAMES = frozenset({"x-auto-reply", "x-autoreply"})


def _subject_is_excluded(subject: str, patterns: list[str]) -> bool:
    """Return ``True`` if *subject* matches an exclusion pattern.

    Plain strings use case-insensitive substring matching for backward
    compatibility. Patterns with shell wildcards (``*`` or ``?``) match the
    full subject while treating square brackets literally.
    """
    lower = subject.lower()
    for pattern in patterns:
        normalized = pattern.lower()
        if "*" in normalized or "?" in normalized:
            wildcard_pattern = re.escape(normalized)
            wildcard_pattern = wildcard_pattern.replace(r"\*", ".*").replace(r"\?", ".")
            if re.fullmatch(wildcard_pattern, lower):
                return True
            continue
        if normalized in lower:
            return True
    return False


def _gmail_headers(msg_raw: dict[str, Any]) -> dict[str, str]:
    """Return normalized message headers keyed by lowercase header name."""
    raw_headers = msg_raw.get("headers", {})
    if not isinstance(raw_headers, dict):
        return {}
    headers: dict[str, str] = {}
    for name, value in raw_headers.items():
        key = str(name).lower().strip()
        if not key:
            continue
        headers[key] = str(value).strip()
    return headers


def _gmail_intent(msg_raw: dict[str, Any]) -> str:
    """Return the normalized crew-chief intent header, if present."""
    return _gmail_headers(msg_raw).get(_CREW_CHIEF_INTENT_HEADER, "").strip().lower()


def _gmail_service_name(msg_raw: dict[str, Any]) -> str:
    """Return the normalized portfolio service header, if present."""
    return _gmail_headers(msg_raw).get(_PORTFOLIO_SERVICE_HEADER, "").strip().lower()


def _is_explicit_crew_chief_request(msg_raw: dict[str, Any], subject: str, body: str) -> bool:
    """Return ``True`` when an email explicitly declares itself as a request."""
    intent = _gmail_intent(msg_raw)
    if intent:
        return intent == _CREW_CHIEF_REQUEST_INTENT

    subject_lower = subject.strip().lower()
    body_lower = body.lstrip().lower()
    if subject_lower.startswith(_CREW_CHIEF_SUBJECT_PREFIX) or body_lower.startswith(
        _CREW_CHIEF_SUBJECT_PREFIX
    ):
        return True
    # User replies to portfolio service notification emails (e.g. "Re: [intake] Receipt processed:")
    # are treated as explicit correction requests even without a [crew-chief] prefix.
    return any(subject_lower.startswith(prefix) for prefix in _SERVICE_REPLY_SUBJECT_PREFIXES)


def _gmail_body_text(msg_raw: dict[str, Any]) -> str:
    """Return the best available plain-text body from a normalized Gmail message."""
    for key in ("text", "body", "snippet"):
        value = msg_raw.get(key, "")
        if isinstance(value, str) and value:
            return value
    return ""


def _gmail_body_candidates(msg_raw: dict[str, Any]) -> list[str]:
    """Return body-like fields worth scanning for loop markers."""
    candidates: list[str] = []
    for key in ("text", "body", "snippet", "html"):
        value = msg_raw.get(key, "")
        if isinstance(value, str) and value:
            candidates.append(value)
    return candidates


def _gmail_message_fingerprint(msg: IncomingMessage) -> str:
    """Return a stable identifier for a Gmail message across poll cycles."""
    raw = msg.raw if isinstance(msg.raw, dict) else {}
    message_id = str(raw.get("message_id") or "").strip()
    if message_id:
        return f"message_id:{message_id}"

    mailbox = str(raw.get("mailbox") or "").strip()
    uid = str(raw.get("uid") or "").strip()
    if mailbox and uid:
        return f"uid:{mailbox}:{uid}"

    timestamp = str(raw.get("timestamp") or "").strip()
    sender = msg.sender.strip().lower()
    subject = msg.subject.strip().lower()
    preview = msg.text.strip().lower()[:200]
    return f"fallback:{sender}|{subject}|{timestamp}|{preview}"


def _claim_gmail_message(msg: IncomingMessage, seen_fingerprints: set[str]) -> bool:
    """Return ``True`` only the first time a Gmail message is observed."""
    fingerprint = _gmail_message_fingerprint(msg)
    if fingerprint in seen_fingerprints:
        log.info("Gmail: skipping already-processed message %s from %s.", fingerprint, msg.sender)
        return False
    seen_fingerprints.add(fingerprint)
    return True


def _is_auto_reply(msg_raw: dict) -> bool:
    """Return ``True`` if *msg_raw* carries standard auto-reply email headers.

    Checks:
    - ``X-Auto-Reply`` / ``X-Autoreply``: presence alone is sufficient.
    - ``Auto-Submitted``: any value other than ``"no"`` (RFC 3834).
    - ``Precedence: auto_reply | bulk | junk``.

    Returns ``False`` when no ``headers`` dict is present (e.g. older
    check_inbox.py output that doesn't expose raw headers).
    """
    headers: dict = msg_raw.get("headers", {})
    if not isinstance(headers, dict):
        return False
    for name, value in headers.items():
        key = name.lower().strip()
        val = str(value).lower().strip()
        if key in _AUTO_REPLY_HEADER_NAMES:
            return True
        if key == "auto-submitted" and val != "no":
            return True
        if key == "precedence" and val in ("auto_reply", "bulk", "junk"):
            return True
    return False


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
    agent: Agent | AgentCascade | None = None,
) -> bool:
    """Interpret, dispatch, and reply to a single incoming message.

    When *agent* is provided (``cfg.agent.enabled = True``), the message text
    is handed directly to the multi-step Agent loop (or cascade).  Otherwise
    the original single-command dispatch flow is used.

    Returns ``True`` if a reply was sent, ``False`` if the message was dropped
    (e.g. no actionable command in single-command mode).
    """
    log.info("[%s] Message from %s: %r", msg.channel, msg.sender, msg.text[:80])

    if agent is not None:
        log.info("[%s] Routing to agent loop.", msg.channel)
        reply_text = agent.run(msg.text)
        model_label = getattr(agent, "last_used_model", "") or "unknown"
        model_header = f"[Model: {model_label}]"
    else:
        command = resolve_command(msg.text, cfg, llm_client)
        if command is None:
            log.info("[%s] No actionable command extracted from message.", msg.channel)
            return False

        # Determine whether a model was involved in routing this command.
        if msg.text.strip().startswith(DIRECT_PREFIX):
            model_header = "[Model: none — direct command]"
        else:
            model_header = f"[Model: {llm_client.model} (command routing)]"

        log.info("[%s] Dispatching: %r", msg.channel, command)
        result: DispatchResult = dispatcher.run(command)
        reply_text = result.reply_text()

    reply_text = f"{model_header}\n\n{reply_text}"
    log.info("[%s] Reply (%d chars): %r", msg.channel, len(reply_text), reply_text[:80])

    if msg.channel == "signal":
        reply_signal(cfg.signal, msg.sender, reply_text)
    elif msg.channel == "gmail":
        reply_gmail(cfg.gmail, cfg.gmail.reply_to or msg.sender, msg.subject, reply_text)
    return True


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

    # Build the agent (or cascade) if agent mode is enabled.
    agent: Agent | AgentCascade | None = None
    if cfg.agent.enabled:
        import dataclasses

        # Resolve the effective provider chain and timeout for agent tasks.
        agent_provider = cfg.agent.provider or cfg.llm.provider
        agent_chain = cfg.agent.fallback_chain or cfg.llm.fallback_chain
        agent_timeout = cfg.agent.timeout_seconds or cfg.llm.timeout_seconds
        agent_llm_cfg = dataclasses.replace(
            cfg.llm,
            provider=agent_provider,
            fallback_chain=agent_chain,
            timeout_seconds=agent_timeout,
        )

        tools = build_tools(cfg)
        threshold = cfg.agent.confidence_threshold

        if threshold > 0.0 and agent_provider == "fallback":
            # Confidence cascade: one Agent per provider, escalate on low score.
            agents = [
                Agent(
                    provider=build_provider(name, agent_llm_cfg),
                    tools=tools,
                    system_prompt=cfg.agent.system_prompt,
                    max_iterations=cfg.agent.max_iterations,
                    confidence_threshold=threshold,
                )
                for name in agent_chain
            ]
            agent = AgentCascade(agents)
            log.info(
                "Agent cascade enabled (chain=%s, threshold=%.2f, timeout=%ds, "
                "tools=%s, max_iter=%d).",
                agent_chain,
                threshold,
                agent_timeout,
                [t.name for t in tools],
                cfg.agent.max_iterations,
            )
        else:
            # Single agent backed by FallbackProvider (or a named provider).
            provider = get_provider(agent_llm_cfg)
            agent = Agent(
                provider=provider,
                tools=tools,
                system_prompt=cfg.agent.system_prompt,
                max_iterations=cfg.agent.max_iterations,
                confidence_threshold=threshold,
            )
            log.info(
                "Agent mode enabled (provider=%s, timeout=%ds, tools=%s, max_iter=%d).",
                agent_provider,
                agent_timeout,
                [t.name for t in tools],
                cfg.agent.max_iterations,
            )

    log.info(
        "crew-chief listener started (Signal=%s, Gmail=%s, interval=%ds, agent=%s).",
        cfg.signal.enabled,
        cfg.gmail.enabled,
        cfg.poll_interval_seconds,
        cfg.agent.enabled,
    )

    seen_gmail_fingerprints: set[str] = set()

    while True:
        cycle_start = time.monotonic()
        cycle_replies = 0
        max_replies = cfg.max_replies_per_cycle

        for msg in poll_signal(cfg.signal):
            if max_replies > 0 and cycle_replies >= max_replies:
                log.warning(
                    "Reply cap reached (%d/cycle); dropping Signal message from %s. "
                    "Increase listener.max_replies_per_cycle to allow more.",
                    max_replies,
                    msg.sender,
                )
                continue
            if _process_message(msg, cfg, llm_client, dispatcher, agent):
                cycle_replies += 1

        for msg in poll_gmail(cfg.gmail):
            if max_replies > 0 and cycle_replies >= max_replies:
                log.warning(
                    "Reply cap reached (%d/cycle); dropping Gmail message from %s. "
                    "Increase listener.max_replies_per_cycle to allow more.",
                    max_replies,
                    msg.sender,
                )
                continue
            if not _claim_gmail_message(msg, seen_gmail_fingerprints):
                continue
            if _process_message(msg, cfg, llm_client, dispatcher, agent):
                cycle_replies += 1

        if once:
            break

        elapsed = time.monotonic() - cycle_start
        sleep_for = max(0.0, cfg.poll_interval_seconds - elapsed)
        if sleep_for > 0:
            time.sleep(sleep_for)
