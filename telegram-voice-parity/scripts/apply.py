#!/usr/bin/env python3
"""
Vik View — Telegram Voice Parity setup.

Configures Hermes Agent so that, on Telegram:
  - text in  -> text out (never voice)
  - voice in -> native voice-bubble reply (before text) + transcript-prefixed
    text out ("🔊 ..."), no leaked system notices, correct gender agreement.

Idempotent: safe to re-run. Each step detects "already applied" and skips.
Does three things, in order:
  1. Patches ~/.hermes/config.yaml (ruamel.yaml, preserves formatting).
  2. Appends persona rules to ~/.hermes/SOUL.md (only if missing).
  3. Applies a code patch to the hermes-agent source tree via `git apply`
     (fixes two real hermes-agent bugs — see references/root-causes.md).

Exits non-zero if a step needed manual attention (prints exactly what and
why) — never silently corrupts a file it can't confidently patch.

Usage:
    python3 apply.py [--dry-run] [--skip-restart]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
PATCH_PATH = SKILL_DIR / "references" / "voice-parity-fixes.patch"

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
HERMES_AGENT_DIR = HERMES_HOME / "hermes-agent"
CONFIG_PATH = HERMES_HOME / "config.yaml"
SOUL_PATH = HERMES_HOME / "SOUL.md"

SOUL_MARKER = "## Formato no Telegram"
SOUL_ADDITION = """
## Gênero e concordância
Você é uma entidade **masculina**. Toda concordância sobre si mesmo é no masculino ("estou pronto", "fui informado").

## Formato no Telegram
- Entrada em texto → responda apenas em texto, normalmente.
- Entrada por voz: chega até você como uma transcrição entre aspas (ex.: "conteúdo transcrito") — texto digitado pelo usuário nunca chega dessa forma. Ao identificar esse padrão, inicie sua resposta em texto com "🔊 ". O áudio já é enviado automaticamente pelo sistema, antes do texto — **nunca chame a ferramenta `text_to_speech` você mesmo** nesses casos, isso duplica ou corrompe o áudio.
- Jamais mencione ou reproduza avisos internos do sistema (home channel, compactação de contexto, tokens, limites de provedor, etc.) nas respostas — esses avisos não são assunto seu.
"""


def _log(msg: str) -> None:
    print(msg, flush=True)


def preflight() -> list[str]:
    """Return a list of blocking problems; empty list = OK to proceed."""
    problems = []
    if not CONFIG_PATH.is_file():
        problems.append(f"config.yaml not found at {CONFIG_PATH}")
    if not SOUL_PATH.is_file():
        problems.append(f"SOUL.md not found at {SOUL_PATH}")
    if not (HERMES_AGENT_DIR / ".git").is_dir():
        problems.append(
            f"{HERMES_AGENT_DIR} is not a git checkout — cannot apply the "
            "code patch safely. This skill only supports the standard "
            "native installer layout."
        )
    if problems:
        return problems

    try:
        import yaml  # noqa: F401
    except ImportError:
        pass
    try:
        with open(CONFIG_PATH) as f:
            import ruamel.yaml as _ry  # noqa: F401
    except ImportError:
        problems.append(
            "ruamel.yaml not importable in this Python — activate the "
            "hermes-agent venv first: source ~/.hermes/hermes-agent/venv/bin/activate"
        )
        return problems

    from ruamel.yaml import YAML
    yaml = YAML()
    with open(CONFIG_PATH) as f:
        cfg = yaml.load(f) or {}
    tts_cfg = cfg.get("tts") or {}
    if not tts_cfg.get("provider"):
        problems.append(
            "tts.provider is not set in config.yaml — this skill assumes "
            "voice mode is already configured (see the base Hermes install "
            "briefing, Fase 4/5). Run `hermes setup` first."
        )
    if not cfg.get("stt", {}).get("enabled", True) is True:
        pass  # stt defaults to enabled; only warn if explicitly disabled
    platform_toolsets = cfg.get("platform_toolsets") or {}
    if "telegram" not in platform_toolsets:
        problems.append(
            "No 'telegram' entry under platform_toolsets in config.yaml — "
            "Telegram gateway doesn't look configured yet (TELEGRAM_BOT_TOKEN "
            "in ~/.hermes/.env, gateway restarted at least once)."
        )
    return problems


def apply_config(dry_run: bool) -> bool:
    """Patch config.yaml. Returns True if any change was made."""
    from ruamel.yaml import YAML
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString as DQ

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 10_000  # don't reflow long lines (personalities block, etc.)

    with open(CONFIG_PATH) as f:
        data = yaml.load(f)

    changed = False

    # 1. Suppress tool-progress bubbles ("Terminal...", "Scheduling create")
    #    from leaking into Telegram chat. MUST be the literal string "off"
    #    (not a YAML boolean) — gateway/run.py compares `progress_mode != "off"`.
    #    A bare `off:` in YAML 1.1 parses as boolean False, which silently
    #    fails this check, so it is force-quoted here.
    display = data.setdefault("display", {})
    platforms = display.setdefault("platforms", {})
    telegram_display = platforms.setdefault("telegram", {})
    if str(telegram_display.get("tool_progress", "")) != "off":
        telegram_display["tool_progress"] = DQ("off")
        changed = True
        _log("  [config] display.platforms.telegram.tool_progress = \"off\"")
    else:
        _log("  [config] display.platforms.telegram.tool_progress already \"off\" — skip")

    # 2. Suppress the daily "Session automatically reset..." chat announcement
    #    (the reset itself still happens — this only mutes the notice).
    session_reset = data.setdefault("session_reset", {})
    if session_reset.get("notify") is not False:
        session_reset["notify"] = False
        changed = True
        _log("  [config] session_reset.notify = false")
    else:
        _log("  [config] session_reset.notify already false — skip")

    # 3. Prevent the model from calling text_to_speech as an explicit tool.
    #    Voice replies are already handled automatically by the gateway
    #    (base adapter auto-TTS / _send_voice_reply); a model-initiated call
    #    bypasses that path and produces broken/duplicate audio.
    agent_cfg = data.setdefault("agent", {})
    disabled = agent_cfg.setdefault("disabled_toolsets", [])
    if "tts" not in [str(x) for x in disabled]:
        disabled.append("tts")
        changed = True
        _log("  [config] agent.disabled_toolsets += tts")
    else:
        _log("  [config] agent.disabled_toolsets already contains tts — skip")

    if changed and not dry_run:
        backup = CONFIG_PATH.with_suffix(".yaml.bak")
        backup.write_text(CONFIG_PATH.read_text())
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(data, f)
        _log(f"  [config] wrote {CONFIG_PATH} (backup: {backup})")
    elif changed and dry_run:
        _log("  [config] (dry-run — no changes written)")

    return changed


def apply_soul(dry_run: bool) -> bool:
    """Append persona rules to SOUL.md. Returns True if a change was made."""
    content = SOUL_PATH.read_text()
    if SOUL_MARKER in content:
        _log("  [soul] SOUL.md already has the Telegram-format section — skip")
        return False

    if not dry_run:
        backup = SOUL_PATH.with_suffix(".md.bak")
        backup.write_text(content)
        with open(SOUL_PATH, "a") as f:
            f.write(SOUL_ADDITION)
        _log(f"  [soul] appended persona rules to {SOUL_PATH} (backup: {backup})")
    else:
        _log("  [soul] (dry-run — would append persona rules)")
    return True


def apply_code_patch(dry_run: bool) -> tuple[bool, bool]:
    """Apply the hermes-agent source patch via git apply.

    Returns (changed, ok). ok=False means manual review is needed — the
    patch neither applies cleanly nor detects as already-applied, which
    means the installed hermes-agent version has drifted from the one this
    patch was written against.
    """
    def _git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(HERMES_AGENT_DIR), *args],
            capture_output=True, text=True,
        )

    already = _git("apply", "--check", "--reverse", str(PATCH_PATH))
    if already.returncode == 0:
        _log("  [code] patch already applied — skip")
        return False, True

    fresh_check = _git("apply", "--check", str(PATCH_PATH))
    if fresh_check.returncode != 0:
        _log("  [code] ✗ patch does not apply cleanly to the installed hermes-agent version.")
        _log("         This usually means hermes-agent was updated (`hermes update`) and the")
        _log("         surrounding code shifted. Manual review needed — see:")
        _log(f"         {PATCH_PATH}")
        _log("         git apply --check output:")
        for line in fresh_check.stderr.strip().splitlines():
            _log(f"           {line}")
        return False, False

    if dry_run:
        _log("  [code] (dry-run — patch would apply cleanly)")
        return True, True

    result = _git("apply", str(PATCH_PATH))
    if result.returncode != 0:
        _log("  [code] ✗ git apply failed unexpectedly after a clean --check:")
        _log(f"         {result.stderr}")
        return False, False

    _log("  [code] applied voice-parity-fixes.patch to gateway/run.py, "
         "gateway/platforms/base.py, tools/tts_tool.py")
    return True, True


def restart_gateway(dry_run: bool) -> None:
    if dry_run:
        _log("  [restart] (dry-run — would run: systemctl --user restart hermes-gateway)")
        return
    result = subprocess.run(
        ["systemctl", "--user", "restart", "hermes-gateway"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        _log(f"  [restart] ✗ failed: {result.stderr.strip()}")
        _log("  [restart] restart manually: systemctl --user restart hermes-gateway")
    else:
        _log("  [restart] hermes-gateway restarted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing")
    parser.add_argument("--skip-restart", action="store_true", help="Don't restart hermes-gateway at the end")
    args = parser.parse_args()

    _log("Vik View — Telegram Voice Parity setup")
    _log(f"HERMES_HOME={HERMES_HOME}")
    _log("")

    problems = preflight()
    if problems:
        _log("✗ Preflight failed — fix these first:")
        for p in problems:
            _log(f"  - {p}")
        return 1

    _log("1/3 config.yaml")
    cfg_changed = apply_config(args.dry_run)

    _log("2/3 SOUL.md")
    soul_changed = apply_soul(args.dry_run)

    _log("3/3 hermes-agent source patch")
    code_changed, code_ok = apply_code_patch(args.dry_run)

    _log("")
    if not code_ok:
        _log("✗ Done with issues — the code patch needs manual review (see above).")
        _log("  config.yaml and SOUL.md changes were still applied.")
        return 1

    any_changed = cfg_changed or soul_changed or code_changed
    if any_changed and not args.skip_restart:
        _log("Restarting gateway to pick up changes...")
        restart_gateway(args.dry_run)
    elif not any_changed:
        _log("Nothing to do — already fully configured.")

    _log("")
    _log("✓ Setup complete. Run scripts/verify.py, then the manual Telegram")
    _log("  test matrix in SKILL.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
