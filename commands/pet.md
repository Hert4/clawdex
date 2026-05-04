---
description: Control the desktop pet companion (start/stop/switch petdex pet)
argument-hint: [start|stop|switch|list|status|scale|state] [name|value]
allowed-tools: Bash(python3:*), Bash(npx petdex install:*)
---

The user typed `/pet $ARGUMENTS` to control their clawdex desktop pet.

Resolve the arguments and run the launcher at `${CLAUDE_PLUGIN_ROOT}/src/ctl.py` via `python3`.

**Argument resolution rules:**

1. **Empty `$ARGUMENTS`** → run `python3 ${CLAUDE_PLUGIN_ROOT}/src/ctl.py status`
2. **First arg is a known subcommand** (`start`, `stop`, `restart`, `switch`, `list`, `status`, `scale`, `state`) → pass through: `python3 ${CLAUDE_PLUGIN_ROOT}/src/ctl.py $ARGUMENTS`
3. **First arg is anything else** (a pet name like `boba`, `akane`, `academicasi`) → treat as switch: `python3 ${CLAUDE_PLUGIN_ROOT}/src/ctl.py switch <arg>`
4. If the launcher reports the pet isn't installed, suggest `npx petdex install <name>` and offer to run it.

**After running**, report the result concisely (1 line). If switching pet, mention the new pet name. Don't list all subcommands unless explicitly asked.

**Examples:**
- `/pet boba` → `ctl.py switch boba`
- `/pet stop` → `ctl.py stop`
- `/pet list` → `ctl.py list`
- `/pet scale 0.4` → `ctl.py scale 0.4`
- `/pet` → `ctl.py status`
