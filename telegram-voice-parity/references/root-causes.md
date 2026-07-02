# Root causes — Telegram voice parity bugs

Reference material for `apply.py` / `verify.py` and for the upstream bug
reports. Written against:

```
Hermes Agent v0.18.0 (2026.7.1) · upstream 88d1d620
commit 88d1d6206f399c134d1f4c0b7db27733aaa3c50c (2026-07-02)
repo: https://github.com/NousResearch/hermes-agent
```

## Bug 1 — Edge TTS silently mislabels MP3 as `.ogg` when given an explicit `.ogg` output_path

**Where:** `tools/tts_tool.py`, `text_to_speech_tool()`, the Edge-TTS
generation branch (`else: # Default: Edge TTS`), and the later
"Try Opus conversion for Telegram compatibility" block.

**What happens:** `edge_tts.Communicate.save(output_path)` always writes
raw MP3-encoded bytes, regardless of the filename extension it's given —
it does no container/codec conversion itself. When a caller (e.g.
`gateway/run.py`'s `_send_voice_reply`, which hardcodes
`audio_ext = "ogg" if platform == Telegram else "mp3"` and passes that
path straight through as `output_path`) explicitly requests a `.ogg`
path, the function saves MP3 bytes under a `.ogg` filename.

The later "convert to Opus" step then does:

```python
elif (
    want_opus
    and provider in {"edge", "neutts", "minimax", "xai", "kittentts", "piper"}
    and not file_str.endswith(".ogg")
):
    opus_path = _convert_to_opus(file_str)
    ...
```

Because `file_str` *already* ends in `.ogg` (the requested filename, not
because it was actually converted), this condition is `False` and the
conversion is skipped entirely. The tool reports success and
`voice_compatible: false`, having produced a file that is literally MP3
data with a `.ogg` extension — `file(1)` reports `MPEG ADTS, layer III`,
not `Ogg data, Opus audio`. Telegram's `sendVoice` API (used for
`.ogg`/`.opus` files) either rejects this or fails to render it as a
native voice bubble.

**Reproduction (isolated, no Telegram needed):**

```python
from tools.tts_tool import text_to_speech_tool
result = text_to_speech_tool(text="test", output_path="/tmp/x.ogg")
# result["voice_compatible"] is False
import subprocess
subprocess.run(["file", "/tmp/x.ogg"])  # -> MPEG ADTS, layer III (not Ogg!)
```

**Fix applied:** when the Edge-TTS branch is asked for a `.ogg` output
path, generate to an `.mp3` sibling path first, then run it through
`_convert_to_opus()` (which already existed and already worked correctly
— it just was never reached), and land the result at the originally
requested `.ogg` path. Also relaxed the later "voice_compatible" `elif`
so it recognizes a path that's *already* real Opus (post-conversion)
instead of only handling the not-yet-`.ogg` case.

**Scope beyond this install:** this affects every install using the
`edge` TTS provider (the default, free option) with any caller that
requests an explicit `.ogg` output_path — not specific to Telegram, not
specific to this config. `neutts`/`kittentts`/`piper` were *not* touched
by this fix — their own generation functions already handle a `.ogg`
target path correctly internally (they write WAV to a temp file and
ffmpeg-convert with `-acodec libopus` themselves), so they don't share
this bug. `minimax`/`xai` were not audited — same `want_opus` elif branch,
unverified whether they have the same issue.

## Bug 2 — Base adapter's auto-TTS can't detect the platform, defaults away from Opus

**Where:** `gateway/platforms/base.py`, the "Auto-TTS: if voice message,
generate audio FIRST" block (~line 4952 at the referenced commit).

**What happens:** this is a *second*, independent automatic voice-reply
mechanism from `gateway/run.py`'s `_send_voice_reply` (the two are
deliberately coordinated — see `_should_send_voice_reply`'s dedup
comment referencing "base adapter auto-TTS"). It calls:

```python
tts_result_str = await asyncio.to_thread(
    text_to_speech_tool, text=speech_text
)
```

with **no `output_path`**. Without an explicit path,
`text_to_speech_tool` falls back to its own default path selection:

```python
elif want_opus and provider in {"openai", "elevenlabs", "mistral", "gemini"}:
    file_path = out_dir / f"tts_{timestamp}.ogg"
else:
    file_path = out_dir / f"tts_{timestamp}.mp3"
```

`want_opus` comes from `get_session_env("HERMES_SESSION_PLATFORM", "")`
(a `contextvars.ContextVar`-backed lookup, `gateway/session_context.py`).
This adapter-level code path runs outside the scope where
`gateway/run.py`'s `_set_session_env()` has bound that contextvar for the
current turn (confirmed empirically: an isolated call with
`HERMES_SESSION_PLATFORM=telegram` set via `os.environ` — the fallback
`get_session_env` uses when the contextvar was never set — correctly
produces `.ogg` + `voice_compatible: true`; the live gateway, in this
exact code path, does not). The provider is `edge` (not in the
opus-native set `{openai, elevenlabs, mistral, gemini}`), so it silently
falls back to `.mp3` — sent as a generic Telegram audio-file attachment
(`sendAudio`) instead of a native voice bubble (`sendVoice`).

Symptom in the logs: `TTS audio saved: .../tts_<timestamp>.mp3` with the
**default** timestamp-based filename pattern — distinguishable from
`_send_voice_reply`'s explicit `tts_reply_<uuid>.<ext>` pattern, which is
how this was traced to `base.py` rather than `gateway/run.py`.

**Fix applied:** `self.platform` is available directly on the adapter
instance at this call site (it's used two lines later, for the caption
logic) — no need to depend on the contextvar at all. Build an explicit
`output_path` with the correct extension (`ogg` for
`Platform.TELEGRAM`, `mp3` otherwise) before calling
`text_to_speech_tool`, mirroring what `_send_voice_reply` already does.

**Scope beyond this install:** affects every Telegram (or any other
platform using this base-adapter auto-TTS path) install using a
non-opus-native TTS provider (`edge`, `neutts`, `minimax`, `xai`,
`kittentts`, `piper`) for the `voice.auto_tts` / `/voice on|tts`
auto-reply feature — not specific to this config.

## Not a bug — config/persona items

The remaining three changes this skill makes are legitimate
environment-specific configuration, not framework bugs:

- `display.platforms.telegram.tool_progress: "off"` — tool-progress
  bubbles are a deliberate, documented, opt-in-by-default feature
  (`display.tool_progress`); this install just prefers them off for
  Telegram. The **type** pitfall (bare `off:` parsing as YAML boolean
  `False`, silently no-oping the `progress_mode != "off"` check in
  `gateway/run.py`) is worth flagging upstream as a footgun regardless —
  a config validator or a `hermes doctor` check for this specific
  bool-vs-string mismatch would prevent a silent misconfiguration.
- `session_reset.notify: false` — existing, documented toggle
  (`SessionResetPolicy.notify`), just not on by default.
- `agent.disabled_toolsets: [tts]` — existing, documented mechanism, used
  here as a defense-in-depth measure (turned out not to be the actual fix
  for either bug above, but is kept: it stops the model from ever
  proactively narrating with voice on a platform where the golden rule is
  "text in -> text out only").
- The `_TELEGRAM_NOISY_STATUS_RE` addition (Codex-gpt-5.5 autoraise
  notice) is a one-line extension of an existing, actively-maintained
  regex whose whole purpose is exactly this kind of suppression — a
  reasonable upstream PR on its own, low risk.

## Upstream issues filed

1. **Edge TTS `.ogg` output_path produces mislabeled MP3, not real Opus**
   (Bug 1) — https://github.com/NousResearch/hermes-agent/issues/57048
2. **Base adapter auto-TTS defaults to `.mp3` on Telegram (no Opus voice
   bubble) because platform detection isn't available in that code path**
   (Bug 2) — https://github.com/NousResearch/hermes-agent/issues/57049

If either lands upstream and `hermes update` picks it up, `apply.py`'s
patch step will detect the corresponding hunk no longer applies and stop
with a clear message — check the issue status before attempting a manual
port at that point.
