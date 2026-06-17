#!/usr/bin/env python3
"""clawdex control script — cross-platform, multi-session pet launcher.

Subcommands:
    hook <subcmd>      Invoked by Claude Code hooks. Reads JSON payload from
                       stdin to extract session_id, then dispatches.
    start [pet]        Spawn a pet for this session.
    stop               Stop this session's pet.
    restart [pet]      Stop + start.
    switch <pet>       Switch to a different pet for this session.
    state <name>       Set pet state (idle, review, running, jumping, etc.).
    scale <factor>     Rescale all running pets.
    list               List installed petdex pets.
    status             Show all running pets across sessions.

Per-session data lives at ~/.clawdex/sessions/<session_id>/.
The active pet name (default 'akane') is stored at ~/.clawdex/active.txt.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
CLAWDEX_DIR = HOME / ".clawdex"
SESSIONS_DIR = CLAWDEX_DIR / "sessions"
ACTIVE_FILE = CLAWDEX_DIR / "active.txt"
SCALE_FILE = CLAWDEX_DIR / "scale.txt"
PETDEX_DIR = Path(os.environ.get("PETDEX_DIR", str(HOME / ".codex" / "pets")))
DEFAULT_PET = "akane"
DEFAULT_SCALE = 0.5
IS_WINDOWS = platform.system() == "Windows"


def ensure_dirs() -> None:
    CLAWDEX_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(exist_ok=True)


def session_dir(sid: str) -> Path:
    d = SESSIONS_DIR / sid
    d.mkdir(parents=True, exist_ok=True)
    return d


def active_pet() -> str:
    if ACTIVE_FILE.exists():
        return ACTIVE_FILE.read_text().strip() or DEFAULT_PET
    return DEFAULT_PET


def set_active(name: str) -> None:
    ensure_dirs()
    ACTIVE_FILE.write_text(name)


def active_scale() -> float:
    if SCALE_FILE.exists():
        try:
            return float(SCALE_FILE.read_text().strip())
        except ValueError:
            pass
    return DEFAULT_SCALE


def set_scale(scale: float) -> None:
    ensure_dirs()
    SCALE_FILE.write_text(str(scale))


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
    return True


def read_pid(d: Path) -> int | None:
    pidf = d / "pid"
    if not pidf.exists():
        return None
    try:
        pid = int(pidf.read_text().strip())
    except (ValueError, OSError):
        return None
    return pid if pid_alive(pid) else None


def write_pid(d: Path, pid: int) -> None:
    (d / "pid").write_text(str(pid))


def clear_pid(d: Path) -> None:
    pidf = d / "pid"
    if pidf.exists():
        pidf.unlink()


def kill_pid(pid: int) -> None:
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.kill(pid, 15)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def cleanup_stale() -> None:
    """Drop stale pid/slot files; remove dirs whose pet AND parent are gone."""
    if not SESSIONS_DIR.exists():
        return
    import shutil
    for d in SESSIONS_DIR.iterdir():
        if not d.is_dir():
            continue
        pid = read_pid(d)
        if pid is not None:
            continue
        clear_pid(d)
        slot_f = d / "slot"
        if slot_f.exists():
            slot_f.unlink()
        # If the parent Claude Code process is also gone, garbage-collect the
        # whole session dir — otherwise dead sessions accumulate forever.
        cp_f = d / "claude_pid"
        if cp_f.exists():
            try:
                cp = int(cp_f.read_text().strip())
                if not pid_alive(cp):
                    shutil.rmtree(d)
            except (ValueError, OSError):
                pass


def live_sessions() -> list[tuple[str, int]]:
    cleanup_stale()
    out = []
    if not SESSIONS_DIR.exists():
        return out
    for d in sorted(SESSIONS_DIR.iterdir()):
        pid = read_pid(d)
        if pid is not None:
            out.append((d.name, pid))
    return out


def find_free_slot() -> int:
    """Return the lowest non-negative integer slot not currently held by a live session."""
    used: set[int] = set()
    for sid, _ in live_sessions():
        slot_f = SESSIONS_DIR / sid / "slot"
        if slot_f.exists():
            try:
                used.add(int(slot_f.read_text().strip()))
            except (ValueError, OSError):
                pass
    i = 0
    while i in used:
        i += 1
    return i


def find_claude_pid() -> int | None:
    """Walk up the process tree to find the Claude Code process.

    When invoked from a hook, the chain is:
        Claude Code → shell → ctl.py
    so the grandparent of this process is Claude Code. Returns None if psutil
    is missing or the walk fails (e.g., manual CLI invocation outside a hook).
    """
    try:
        import psutil  # type: ignore
        me = psutil.Process()
        parent = me.parent()
        if parent is None:
            return None
        gp = parent.parent()
        return gp.pid if gp is not None else None
    except Exception:
        return None


def hook_session_id() -> str:
    """Read JSON payload from stdin and extract session_id, fallback to 'default'."""
    if sys.stdin.isatty():
        return "default"
    try:
        raw = sys.stdin.read()
    except Exception:
        return "default"
    if not raw.strip():
        return "default"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "default"
    return str(data.get("session_id") or data.get("sessionId") or "default")


def ensure_deps() -> None:
    """Auto-install PyQt5 + Pillow + psutil (and pyobjc on macOS) if missing."""
    missing = []
    try:
        import PyQt5  # noqa: F401
    except ImportError:
        missing.append("PyQt5")
    try:
        import PIL  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    try:
        import psutil  # noqa: F401
    except ImportError:
        missing.append("psutil")
    if sys.platform == "darwin":
        # pyobjc lets the pet float above other apps and drop its Dock icon.
        try:
            import AppKit  # noqa: F401
        except ImportError:
            missing.append("pyobjc-framework-Cocoa")
    if not missing:
        return
    print(f"clawdex: installing missing deps: {', '.join(missing)}", file=sys.stderr)
    cmd = [sys.executable, "-m", "pip", "install", "--user", "--quiet"] + missing
    try:
        subprocess.run(cmd, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(
            f"clawdex: failed to auto-install deps ({e}). "
            f"Run manually: pip install --user {' '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)


def pet_script() -> Path:
    return Path(__file__).parent / "pet.py"


def spawn_pet(sid: str, pet_name: str, scale: float, idx: int) -> int:
    """Spawn pet.py detached. Returns child PID."""
    sd = session_dir(sid)
    log = (sd / "log").open("a")
    args = [
        sys.executable,
        str(pet_script()),
        "--pet", pet_name,
        "--scale", str(scale),
        "--session", sid,
        "--position-index", str(idx),
    ]
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": log,
        "stderr": subprocess.STDOUT,
        "cwd": str(Path(__file__).parent),
    }
    if IS_WINDOWS:
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(args, **kwargs)
    return proc.pid


# ─── command handlers ──────────────────────────────────────────────────────

def cmd_start(sid: str, pet_name: str | None) -> int:
    ensure_dirs()
    cleanup_stale()
    sd = session_dir(sid)
    if read_pid(sd) is not None:
        return 0  # already running
    name = pet_name or active_pet()
    if not (PETDEX_DIR / name / "spritesheet.webp").exists():
        print(
            f"clawdex: pet '{name}' not installed at {PETDEX_DIR / name}.\n"
            f"  Install: npx petdex install {name}",
            file=sys.stderr,
        )
        return 1
    if pet_name:
        set_active(pet_name)
    ensure_deps()
    (sd / "state").write_text("idle")
    # Preserve slot from a prior run (e.g. mid-switch) so the pet stays in place.
    if not (sd / "slot").exists():
        (sd / "slot").write_text(str(find_free_slot()))
    slot = int((sd / "slot").read_text().strip())
    # Preserve claude_pid across switch/scale restarts — that file points at the
    # actual Claude Code process for this session, so each session's pet keeps
    # tracking its own parent rather than whoever invoked the switch.
    if not (sd / "claude_pid").exists():
        claude_pid = find_claude_pid()
        if claude_pid is not None:
            (sd / "claude_pid").write_text(str(claude_pid))
    pid = spawn_pet(sid, name, active_scale(), slot)
    write_pid(sd, pid)
    time.sleep(0.4)
    if not pid_alive(pid):
        clear_pid(sd)
        log = (sd / "log").read_text() if (sd / "log").exists() else ""
        print(f"clawdex: pet failed to start. Log:\n{log}", file=sys.stderr)
        return 1
    print(f"clawdex: started {name} for session {sid} (pid {pid})")
    return 0


def cmd_stop(sid: str) -> int:
    """Wave goodbye, then stop and clean up. Used for real session end."""
    cleanup_stale()
    sd = SESSIONS_DIR / sid
    if not sd.exists():
        return 0
    pid = read_pid(sd)
    if pid is not None:
        # Ask the pet to play the farewell animation; it self-quits when done.
        (sd / "state").write_text("farewell")
        # Farewell duration is ~700ms; give a small buffer for the poll loop.
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if not pid_alive(pid):
                break
            time.sleep(0.1)
        # Safety net: if the pet still hasn't exited, force kill it.
        if pid_alive(pid):
            kill_pid(pid)
    clear_pid(sd)
    for ephemeral in ("slot", "claude_pid"):
        f = sd / ephemeral
        if f.exists():
            f.unlink()
    print(f"clawdex: stopped session {sid}")
    return 0


def cmd_stop_quick(sid: str) -> None:
    """Kill pet quickly without farewell or claude_pid cleanup.

    Used internally by cmd_switch / cmd_scale to restart a pet in-place
    while preserving its slot and claude_pid for the rebooted window.
    """
    sd = SESSIONS_DIR / sid
    if not sd.exists():
        return
    pid = read_pid(sd)
    if pid is not None:
        kill_pid(pid)
        # Brief wait so the pet exits before we respawn into the same slot.
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and pid_alive(pid):
            time.sleep(0.05)
    clear_pid(sd)


def cmd_state(sid: str, name: str) -> int:
    sd = session_dir(sid)
    (sd / "state").write_text(name)
    return 0


def cmd_switch_global(pet_name: str) -> int:
    """Set active pet and restart every live pet window with the new sprite.

    Each session keeps its slot + claude_pid, so positions and parent watchdogs
    are preserved across the switch.
    """
    if not (PETDEX_DIR / pet_name / "spritesheet.webp").exists():
        print(
            f"clawdex: pet '{pet_name}' not installed at {PETDEX_DIR / pet_name}.\n"
            f"  Install: npx petdex install {pet_name}",
            file=sys.stderr,
        )
        return 1
    set_active(pet_name)
    sessions = [sid for sid, _ in live_sessions()]
    if not sessions:
        print(f"clawdex: active pet set to {pet_name} (no live pets to restart)")
        return 0
    for sid in sessions:
        cmd_stop_quick(sid)
    for sid in sessions:
        cmd_start(sid, None)
    print(f"clawdex: switched {len(sessions)} pet(s) to {pet_name}")
    return 0


def cmd_switch_session(sid: str, pet_name: str) -> int:
    """Per-session switch — preserves slot/claude_pid, only swaps sprite."""
    cmd_stop_quick(sid)
    return cmd_start(sid, pet_name)


def cmd_list() -> int:
    if not PETDEX_DIR.exists():
        print(f"clawdex: petdex dir {PETDEX_DIR} not found. Install: npx petdex install <name>")
        return 1
    pets = sorted(d.name for d in PETDEX_DIR.iterdir() if d.is_dir())
    cur = active_pet()
    print(f"Installed pets in {PETDEX_DIR}:")
    for p in pets:
        marker = "* " if p == cur else "  "
        print(f"  {marker}{p}")
    return 0


def cmd_status() -> int:
    sessions = live_sessions()
    if not sessions:
        print("clawdex: no pets running")
        return 0
    print(f"clawdex: {len(sessions)} pet(s) running")
    for sid, pid in sessions:
        sd = SESSIONS_DIR / sid
        state = (sd / "state").read_text().strip() if (sd / "state").exists() else "?"
        print(f"  session {sid}: pid {pid}, state {state}")
    return 0


def cmd_scale(factor: float) -> int:
    """Update global scale and quickly restart every live pet at the new size."""
    set_scale(factor)
    sessions = [sid for sid, _ in live_sessions()]
    for sid in sessions:
        cmd_stop_quick(sid)
    for sid in sessions:
        cmd_start(sid, None)
    print(f"clawdex: scale set to {factor}, restarted {len(sessions)} pet(s)")
    return 0


# ─── arg parsing ───────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="clawdex")
    parser.add_argument("--session", help="Session id (override stdin/default)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_hook = sub.add_parser("hook", help="Invoked by Claude Code hooks")
    p_hook.add_argument("hook_cmd", choices=["start", "stop", "state"])
    p_hook.add_argument("hook_arg", nargs="?")

    sub.add_parser("start").add_argument("pet", nargs="?")
    sub.add_parser("stop")
    p_restart = sub.add_parser("restart"); p_restart.add_argument("pet", nargs="?")
    p_switch = sub.add_parser("switch"); p_switch.add_argument("pet")
    p_state = sub.add_parser("state"); p_state.add_argument("name")
    p_scale = sub.add_parser("scale"); p_scale.add_argument("factor", type=float)
    sub.add_parser("list")
    sub.add_parser("status")

    args = parser.parse_args(argv)

    if args.cmd == "hook":
        sid = args.session or hook_session_id()
        if args.hook_cmd == "start":
            return cmd_start(sid, None)
        if args.hook_cmd == "stop":
            return cmd_stop(sid)
        if args.hook_cmd == "state":
            return cmd_state(sid, args.hook_arg or "idle")
        return 1

    sid = args.session or "default"

    if args.cmd == "start":
        return cmd_start(sid, args.pet)
    if args.cmd == "stop":
        return cmd_stop(sid)
    if args.cmd == "restart":
        cmd_stop(sid); time.sleep(0.2); return cmd_start(sid, args.pet)
    if args.cmd == "switch":
        # --session forces per-session switch; default is global so that
        # `/pet boba` from a slash command (no session_id available) updates
        # all live pets instead of spawning a phantom "default" session.
        if args.session is not None:
            return cmd_switch_session(sid, args.pet)
        return cmd_switch_global(args.pet)
    if args.cmd == "state":
        return cmd_state(sid, args.name)
    if args.cmd == "scale":
        return cmd_scale(args.factor)
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "status":
        return cmd_status()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
