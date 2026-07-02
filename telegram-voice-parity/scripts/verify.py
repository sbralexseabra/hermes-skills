#!/usr/bin/env python3
"""
Vik View — Telegram Voice Parity: automated checks.

Verifies everything that can be checked without a real Telegram round-trip:
  - config.yaml has the three settings applied, with correct types
  - SOUL.md has the persona additions
  - emoji is stripped before TTS synthesis (regression check for the
    "spoken icon" bug)
  - Edge TTS + explicit .ogg output_path produces a *real* Opus file, not
    MP3 bytes mislabeled with a .ogg extension (regression check for the
    voice-bubble bug)

Does NOT verify the live Telegram round-trip (ordering, native bubble
rendering, caption) — that needs a human on the other end. See the manual
test matrix in SKILL.md for that.

Must run with the hermes-agent venv's Python (uses tools.tts_tool).
Usage: python3 verify.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
HERMES_AGENT_DIR = HERMES_HOME / "hermes-agent"
CONFIG_PATH = HERMES_HOME / "config.yaml"
SOUL_PATH = HERMES_HOME / "SOUL.md"

_PASS = "\033[32m✓\033[0m"
_FAIL = "\033[31m✗\033[0m"

_failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global _failures
    mark = _PASS if ok else _FAIL
    print(f"{mark} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        _failures += 1


def check_config() -> None:
    from ruamel.yaml import YAML
    yaml = YAML()
    with open(CONFIG_PATH) as f:
        cfg = yaml.load(f) or {}

    tool_progress = (
        cfg.get("display", {}).get("platforms", {}).get("telegram", {}).get("tool_progress")
    )
    check(
        "display.platforms.telegram.tool_progress == \"off\" (string, not bool)",
        tool_progress == "off" and not isinstance(tool_progress, bool),
        repr(tool_progress),
    )

    notify = cfg.get("session_reset", {}).get("notify")
    check("session_reset.notify is False", notify is False, repr(notify))

    disabled = [str(x) for x in (cfg.get("agent", {}).get("disabled_toolsets") or [])]
    check("agent.disabled_toolsets contains 'tts'", "tts" in disabled, repr(disabled))


def check_soul() -> None:
    content = SOUL_PATH.read_text()
    check("SOUL.md has 'Gênero e concordância' section", "Gênero e concordância" in content)
    check("SOUL.md has 'Formato no Telegram' section", "Formato no Telegram" in content)
    check(
        "SOUL.md instructs starting voice replies with \"🔊 \"",
        '"🔊 "' in content or "🔊 " in content,
    )


def check_emoji_stripped() -> None:
    sys.path.insert(0, str(HERMES_AGENT_DIR))
    from tools.tts_tool import _strip_markdown_for_tts, text_to_speech_tool

    stripped = _strip_markdown_for_tts("🔊 texto de teste")
    check(
        "_strip_markdown_for_tts removes leading emoji",
        stripped == "texto de teste",
        repr(stripped),
    )

    # text_to_speech_tool itself must ALSO strip emoji (defense in depth —
    # this is what actually saved the auto-TTS code path, which does not
    # call _strip_markdown_for_tts before invoking the tool).
    result = json.loads(text_to_speech_tool(text="🔊 outro teste"))
    check(
        "text_to_speech_tool succeeds with emoji-prefixed text",
        result.get("success") is True,
        result.get("error", ""),
    )
    if result.get("success"):
        try:
            os.remove(result["file_path"])
        except OSError:
            pass


def check_opus_conversion() -> None:
    sys.path.insert(0, str(HERMES_AGENT_DIR))
    from tools.tts_tool import text_to_speech_tool

    tmp_ogg = os.path.join(tempfile.gettempdir(), "vik_voice_parity_check.ogg")
    try:
        result = json.loads(
            text_to_speech_tool(text="verificação de bolha de voz", output_path=tmp_ogg)
        )
        check(
            "text_to_speech_tool(output_path=*.ogg) reports voice_compatible=true",
            result.get("voice_compatible") is True,
            json.dumps(result),
        )
        if os.path.isfile(tmp_ogg):
            file_out = subprocess.run(
                ["file", "-b", tmp_ogg], capture_output=True, text=True
            ).stdout.strip()
            check(
                "output file is real Ogg/Opus data (not MP3 mislabeled as .ogg)",
                "Ogg data" in file_out and "Opus" in file_out,
                file_out,
            )
        else:
            check("output file exists", False, "not created")
    finally:
        try:
            os.remove(tmp_ogg)
        except OSError:
            pass


def check_noisy_status_pattern() -> None:
    sys.path.insert(0, str(HERMES_AGENT_DIR))
    from gateway.run import _TELEGRAM_NOISY_STATUS_RE

    sample = (
        "Codex gpt-5.5 caps context at 272K, so auto-compaction was raised "
        "to 70% (from 50%)"
    )
    check(
        "_TELEGRAM_NOISY_STATUS_RE suppresses the Codex gpt-5.5 autoraise notice",
        bool(_TELEGRAM_NOISY_STATUS_RE.search(sample)),
    )


def main() -> int:
    print("Vik View — Telegram Voice Parity: automated checks\n")
    print("config.yaml")
    check_config()
    print("\nSOUL.md")
    check_soul()
    print("\nemoji stripping")
    check_emoji_stripped()
    print("\nOpus conversion (Edge TTS -> real .ogg)")
    check_opus_conversion()
    print("\nnoisy status suppression")
    check_noisy_status_pattern()

    print()
    if _failures:
        print(f"{_failures} check(s) failed. Fix before running the manual Telegram test matrix.")
        return 1
    print("All automated checks passed.")
    print("Now run the manual Telegram test matrix in SKILL.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
