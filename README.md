# clawdex

Animated petdex pets for **Claude Code** — a transparent desktop companion that mirrors your session state. Each Claude Code session gets its own reactive pet that dances along to your work: idle when you're thinking, running when tools fire, jumping when a task lands, waiting when permission is asked.

```
You type a message  ─→  pet pose: review
Claude calls a tool ─→  pet pose: running
Tool succeeds       ─→  pet pose: review
Claude finishes     ─→  pet pose: jumping (then idle)
Claude needs perm   ─→  pet pose: waiting
```

Sprites come from [petdex](https://petdex.crafter.run) — install pets there, clawdex picks them up.

## Install

**Prerequisites**

- Claude Code (any platform: Linux / macOS / Windows)
- Python 3.9+ on `PATH` (PyQt5 + Pillow are auto-installed on first run)
- A working compositor for transparency (Linux X11 with compiz/picom; macOS and Windows 10+ work out of the box)
- `node` / `npx` for petdex sprite installation

**Steps**

```bash
# 1. Install at least one petdex pet (sprite assets)
npx petdex install boba
npx petdex install akane
```

In Claude Code:

```
# 2. Add this repo as a marketplace
/plugin marketplace add Hert4/clawdex

# 3. Install the plugin
/plugin install clawdex@Hert4-clawdex

# 4. Restart Claude Code so SessionStart hook can fire
```

Now your pet appears in the bottom-right corner. Send any message to see it animate.

## Usage

Slash command: `/clawdex:pet` (or `/pet` when there's no name conflict).

| Command | Effect |
|---------|--------|
| `/pet` | show current status |
| `/pet boba` | switch to a different installed pet |
| `/pet list` | list installed petdex pets |
| `/pet scale 0.4` | resize all running pets |
| `/pet stop` | tuck pet away for this session |
| `/pet start` | spawn pet for this session |

Direct CLI from a terminal also works:

```bash
python3 ~/.claude/plugins/clawdex/src/ctl.py status
python3 ~/.claude/plugins/clawdex/src/ctl.py switch boba
python3 ~/.claude/plugins/clawdex/src/ctl.py scale 0.3
```

**Mouse interaction on the pet itself**

- Drag with left-click to reposition
- Double-click to wave
- Right-click for state menu + Quit

## How it reacts to Claude Code

The plugin wires 7 hooks into your session:

| Event | Pet state | Why |
|-------|-----------|-----|
| `SessionStart` | wave → idle | greeting |
| `UserPromptSubmit` | review | reading your message |
| `PreToolUse` | running | working on a tool call |
| `PostToolUse` | review | thinking after tool result |
| `Notification` | waiting | needs your input/permission |
| `Stop` | jumping → idle | finished an answer |
| `SessionEnd` | (window closes) | done |

## Multi-session

Open Claude Code in two terminals or two IDEs at once and you'll see **two pets** — one per session, each reactive only to its own work. They auto-stack from the bottom-right corner so they don't overlap. Each pet has independent state; they won't fight over poses.

Per-session data lives at `~/.clawdex/sessions/<session_id>/`. The active pet name is stored globally at `~/.clawdex/active.txt` (default: `akane`).

## Available pets

Anything in the petdex gallery works — `npx petdex install <name>` and clawdex picks it up. A few starting suggestions:

- `akane` — tsundere maid with red twin tails
- `boba` — otter sipping bubble tea
- `academicasi` — scholar mage with grimoire
- Browse all at [petdex.crafter.run](https://petdex.crafter.run)

## Troubleshooting

**Pet doesn't appear after install**
- Restart your Claude Code session — `SessionStart` hook only fires on new sessions.
- Confirm petdex installed a pet: `ls ~/.codex/pets/`.
- Check the log: `cat ~/.clawdex/sessions/*/log`.
- Try standalone: `python3 ~/.claude/plugins/clawdex/src/pet.py --pet akane --scale 0.5 --session test --position-index 0`.

**No transparency on Linux**
- You need a compositor. On Ubuntu Unity it's built-in; on minimal i3/openbox setups install `picom` or `compton`.

**`pip install` fails on first run**
- Run manually: `pip install --user PyQt5 Pillow` (or use `requirements.txt`).

**Pet "fights" between sessions**
- Should not happen — each session has its own state file. If it does, run `python3 ~/.claude/plugins/clawdex/src/ctl.py status` to see active sessions; stale ones get auto-cleaned next invocation.

## Architecture

```
clawdex/
├── .claude-plugin/
│   ├── plugin.json          # Claude Code plugin manifest
│   └── marketplace.json     # self-hosted marketplace
├── commands/pet.md          # /clawdex:pet slash command
├── hooks/hooks.json         # 7 events → state transitions
└── src/
    ├── ctl.py               # cross-platform launcher (multi-session)
    └── pet.py               # PyQt5 floating window
```

State machine and sprite grid coordinates (`STATES`, `ROW_YS`, `COL_XS` in `pet.py`) are derived empirically from the petdex spritesheet and apply to all petdex pets uniformly.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

- [petdex](https://github.com/crafter-station/petdex) for the sprite gallery and asset pipeline.
- [Claude Code](https://claude.com/claude-code) for the plugin SDK.
