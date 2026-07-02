# hermes-skills

Custom [Hermes Agent](https://github.com/NousResearch/hermes-agent) skills for Vik View, meant to be reused across installations.

## Skills

### [telegram-voice-parity](telegram-voice-parity/)

Configures the Telegram gateway so text-in produces text-out and voice-in produces a native voice-bubble reply (audio first, then a transcript-prefixed text) — no leaked system notices, correct persona gender agreement. Fixes two real hermes-agent bugs along the way (see [`references/root-causes.md`](telegram-voice-parity/references/root-causes.md)).

## Installing a skill from this repo

```bash
hermes skills install sbralexseabra/hermes-skills/<skill-name>
```

e.g.

```bash
hermes skills install sbralexseabra/hermes-skills/telegram-voice-parity
```

Each skill documents its own setup and verification steps in its `SKILL.md`.
