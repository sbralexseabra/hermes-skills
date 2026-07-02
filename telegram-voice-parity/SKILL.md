---
name: telegram-voice-parity
description: Configure Hermes Agent's Telegram gateway so text-in produces text-out and voice-in produces a native voice-bubble reply (with transcript caption) — no leaked system notices, correct gender agreement in the persona. Use when setting up or debugging voice replies on Telegram, when audio arrives as a file attachment instead of a native bubble, when the TTS voice speaks an emoji aloud, or when internal notices ("Session automatically reset...", tool-progress bubbles) leak into the chat.
version: 1.0.0
author: Alex Seabra / Vik View
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [telegram, voice, tts, stt, gateway, setup]
    category: hermes-agent-setup
    related_skills: [hermes-agent-skill-authoring]
---

# Telegram Voice Parity (Vik View)

## Auto-execute on load

**Do not just describe these steps — run them.** When a user asks to set
up, install, or fix Telegram voice replies and this skill loads, treat it
as a standing instruction to act immediately using your terminal tool:

1. Locate this skill's own directory (the folder containing this
   `SKILL.md`) — `scripts/` and `references/` are siblings of it,
   regardless of where the skill was installed from.
2. Run the preflight check implicitly by executing
   `scripts/apply.py --dry-run` first; if it reports missing prerequisites,
   stop and tell the user what's missing instead of guessing.
3. If preflight passes, run `scripts/apply.py` for real (inside the
   hermes-agent venv — activate `~/.hermes/hermes-agent/venv/bin/activate`
   first, or invoke that venv's `python3` directly).
4. Run `scripts/verify.py`. If anything fails, report it verbatim — do not
   silently retry or "fix" the failure yourself; the two scripts are
   idempotent so a human can re-run them safely after investigating.
5. Tell the user setup is done and hand them the manual test matrix below
   (steps 1–7) — that part genuinely needs a human on the Telegram side,
   you cannot complete it yourself.

Only skip straight to explaining rather than running when the user
explicitly asks to just read/preview the skill.

## Goal

On the Hermes Agent Telegram gateway:

- **User sends text → assistant replies with text only.** No audio, ever.
- **User sends voice → in this exact order:**
  1. The user's voice message (Telegram shows it natively).
  2. Its transcription (echoed back automatically, prefixed `🎙️`).
  3. **The assistant's reply as a native voice bubble** (OGG/Opus,
     playable standalone — not a generic audio-file attachment), ideally
     with the reply text attached as the bubble's caption.
  4. If the reply is too long for a Telegram caption (>1024 chars), the
     text is sent as a separate message afterward, starting with `🔊 `.
- **No internal/system notices ever appear in the chat** — session
  resets, tool-progress ("Terminal...", "Scheduling create..."), context
  compaction, home-channel setup, etc. all stay in logs only.
- The persona refers to itself with **masculine** grammatical agreement.

## When to use this skill

Trigger it when the user asks to set up or fix voice replies on Telegram,
or reports any of:
- Voice replies arrive as a downloadable file instead of a playable voice
  bubble.
- The TTS voice says something like "loudspeaker with three sound waves"
  (or similarly odd) before the actual reply — it's reading an emoji aloud.
- System/internal messages ("Session automatically reset...", raw tool
  names) show up in the Telegram chat.
- The assistant refers to itself with feminine grammatical agreement.

## Installing this skill on a new machine

If this skill isn't present yet under `~/.hermes/skills/`, fetch it first:

```bash
hermes skills install sbralexseabra/hermes-skills/telegram-voice-parity
```

This pulls the whole directory (`SKILL.md`, `scripts/`, `references/`)
from https://github.com/sbralexseabra/hermes-skills. The install runs a
security scan first (it's an unusual skill — it patches hermes-agent's
own source and restarts a service); confirm the prompt, or pass `--yes`
in non-interactive contexts. Once installed, follow "Auto-execute on
load" above — a user just needs to ask for Telegram voice parity to be
set up and the rest happens automatically.

## Prerequisites

This skill assumes Hermes Agent is **already installed** with:
- A native (non-Docker) install at `~/.hermes/hermes-agent/`, as a git
  checkout (the installer's default layout).
- `tts.provider` set in `config.yaml` (voice replies already work in some
  form — see the base install skill/briefing if not).
- `stt.enabled: true` (voice input transcription already works).
- Telegram gateway configured and running (`TELEGRAM_BOT_TOKEN` in
  `~/.hermes/.env`, `hermes-gateway` service active).

If any of these aren't true yet, do that first — `scripts/apply.py` will
refuse to run (preflight check) rather than guess.

## What this skill changes

Three layers, all idempotent (safe to re-run):

1. **`~/.hermes/config.yaml`** — three settings (see
   `references/root-causes.md` for why each one is needed):
   - `display.platforms.telegram.tool_progress: "off"` — stop tool-call
     progress bubbles from leaking into the chat. Must be the literal
     **string** `"off"`, not YAML boolean `false` — the code compares
     `progress_mode != "off"`, so a bare `off:` (which YAML 1.1 parses as
     boolean) silently fails to disable anything.
   - `session_reset.notify: false` — the daily session reset still
     happens, it just stops announcing itself in chat.
   - `agent.disabled_toolsets: [tts]` — removes the `text_to_speech` tool
     from what the model can call directly. Voice replies are already
     handled automatically by the gateway; a model-initiated call
     bypasses that path and produces broken or duplicate audio.

2. **`~/.hermes/SOUL.md`** — appends two sections (never removes existing
   content):
   - Masculine grammatical self-reference.
   - How to recognize voice-origin input (arrives wrapped in literal
     quotes, e.g. `"conteúdo transcrito"` — plain typed text never is)
     and start the text reply with `🔊 ` when it is voice-origin, without
     ever calling `text_to_speech` itself.

3. **hermes-agent source** (`references/voice-parity-fixes.patch`,
   applied via `git apply`) — fixes two real bugs in Hermes Agent itself
   (not specific to this install; see `references/root-causes.md` and the
   linked upstream issues):
   - `tools/tts_tool.py`: emoji is stripped before any TTS provider ever
     sees the text (previously it was read aloud via its Unicode
     description).
   - `tools/tts_tool.py`: when a caller asks Edge TTS for `.ogg` output
     explicitly, the code now actually converts to Opus via ffmpeg
     instead of silently saving raw MP3 bytes under a `.ogg` filename
     (which Telegram can't play as a voice bubble).
   - `gateway/platforms/base.py`: the base adapter's automatic voice-reply
     path now passes an explicit, platform-correct output path to the TTS
     tool, instead of relying on session-platform detection that isn't
     available in that code path (silently fell back to `.mp3`).
   - `gateway/run.py`: one more pattern added to the existing
     "noisy status → logs only" filter, covering the Codex-gpt-5.5
     auto-compaction notice.

## How to apply

```bash
cd ~/.hermes/hermes-agent
source venv/bin/activate
python3 <this-skill's-directory>/scripts/apply.py
```

`<this-skill's-directory>` is wherever this `SKILL.md` actually lives —
`~/.hermes/skills/hermes-agent-setup/telegram-voice-parity/` if installed
manually, or wherever `hermes skills install` placed it if installed from
GitHub (e.g. `~/.hermes/skills/<category>/telegram-voice-parity/`). The
scripts locate `HERMES_HOME` and the hermes-agent checkout on their own —
only their own path (relative to `SKILL.md`) varies by install method.

Add `--dry-run` first if you want to see what would change without
writing anything. The script restarts `hermes-gateway` at the end unless
`--skip-restart` is passed.

If the code-patch step reports it can't apply cleanly, hermes-agent has
likely been updated since this patch was written — check whether the two
upstream bugs it fixes have been resolved natively (see
`references/root-causes.md` for the issue links) before attempting a
manual port of the patch.

## Automated verification

```bash
python3 <this-skill's-directory>/scripts/verify.py
```

Checks config values (and their *types* — this is where the `"off"` vs
`false` bug hides), SOUL.md content, emoji stripping, and that Edge TTS
output requested as `.ogg` is genuinely Opus-encoded (not mislabeled MP3).
This does **not** replace the manual test below — it only rules out the
regressions this skill is designed to prevent.

## Manual test matrix (requires a real Telegram round-trip)

Do this with the account the bot is paired to. In the chat with the bot:

1. `/voice on` (enables voice-input handling for this chat if not already).
2. `/sethome` (only needed once per platform — clears the one-time
   home-channel notice).
3. Send a **text** message. Expect: text-only reply, no `🔊`, no audio.
4. Send a **voice** message. Expect, in order: your voice message → its
   transcription echo (🎙️) → the assistant's voice bubble (tap to play —
   should be a round/native player, not a file-with-title) → either the
   reply text as the bubble's caption, or (if long) a separate message
   starting with `🔊 `.
5. Confirm the voice bubble is audibly `pt-BR-AntonioNeural` (or whatever
   `tts.edge.voice` is configured to).
6. Confirm the reply text uses masculine self-reference ("pronto",
   "recebido", never "pronta"/"recebida").
7. Re-read the whole exchange for anything that looks like a system/debug
   notice (tool names, "Session automatically reset", raw file paths,
   provider/context-limit chatter). There should be none.

If any step fails, re-run `scripts/verify.py` first — it catches most
regressions faster than a live Telegram round-trip.

## Known limitations

- Only tested against the hermes-agent version installed at the time this
  skill was written (`hermes --version` — check
  `references/root-causes.md` for the exact commit). A `hermes update`
  may shift the surrounding code enough that the patch stops applying
  cleanly; `apply.py` detects this and refuses to guess. The two code
  bugs this patches are filed upstream:
  [#57048](https://github.com/NousResearch/hermes-agent/issues/57048),
  [#57049](https://github.com/NousResearch/hermes-agent/issues/57049) —
  check their status before manually porting the patch.
- The long-response fallback (plain `🔊 ` text message, no caption) is
  exercised automatically by Telegram's 1024-char caption limit — not
  separately tested by `verify.py`.
- Assumes a single Telegram bot/chat. Multi-profile or multi-bot Hermes
  setups aren't covered.
