#!/usr/bin/env python3
"""clawdex pet — PyQt5 floating window for one Claude Code session.

Reads its state from ~/.clawdex/sessions/<session>/state and animates the
appropriate pose loop. Transient states (waving/jumping/failed) auto-revert
to idle. Window position offsets bottom-right by --position-index so multiple
sessions don't overlap.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from PIL import Image
from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtGui import QImage, QPixmap, QMouseEvent
from PyQt5.QtWidgets import QApplication, QLabel, QMenu, QWidget, QVBoxLayout

HOME = Path.home()
PETDEX_DIR = Path(os.environ.get("PETDEX_DIR", str(HOME / ".codex" / "pets")))
CLAWDEX_DIR = HOME / ".clawdex"

# Empirical sprite-grid coordinates for the standard 1536x1872 petdex sheet,
# derived via alpha-gutter analysis. All petdex pets share this layout.
ROW_YS = [5, 213, 421, 629, 837, 1045, 1253, 1461, 1669]
ROW_H = 198
COL_XS = [5, 197, 389, 581, 773, 965, 1160, 1362]
COL_W = 182

STATES = {
    "idle":          {"row": 0, "frames": 6, "duration": 1100, "transient": False},
    "running_right": {"row": 1, "frames": 8, "duration": 1060, "transient": False},
    "running_left":  {"row": 2, "frames": 8, "duration": 1060, "transient": False},
    "waving":        {"row": 3, "frames": 4, "duration": 700,  "transient": True},
    "jumping":       {"row": 4, "frames": 5, "duration": 840,  "transient": True},
    "failed":        {"row": 5, "frames": 8, "duration": 1220, "transient": True},
    "waiting":       {"row": 6, "frames": 6, "duration": 1010, "transient": False},
    "running":       {"row": 7, "frames": 6, "duration": 820,  "transient": False},
    "review":        {"row": 8, "frames": 6, "duration": 1030, "transient": False},
    # Farewell shares the waving sprite but quits the app when the animation
    # completes instead of falling back to idle. Triggered by ctl.py stop or
    # by the parent watchdog so the pet always says goodbye on the way out.
    "farewell":      {"row": 3, "frames": 4, "duration": 700,  "transient": True, "exit_on_done": True},
}


def pil_to_qpixmap(im: Image.Image) -> QPixmap:
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    qimg = QImage(data, im.width, im.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def load_frames(pet_path: Path, scale: float) -> dict[str, list[QPixmap]]:
    sheet = Image.open(pet_path / "spritesheet.webp").convert("RGBA")
    out: dict[str, list[QPixmap]] = {}
    for name, spec in STATES.items():
        y = ROW_YS[spec["row"]]
        row_frames = []
        for i in range(spec["frames"]):
            x = COL_XS[i]
            cell = sheet.crop((x, y, x + COL_W, y + ROW_H))
            bbox = cell.getbbox()
            cell = cell.crop(bbox) if bbox else cell
            if scale != 1.0:
                w, h = max(1, int(cell.width * scale)), max(1, int(cell.height * scale))
                cell = cell.resize((w, h), Image.LANCZOS)
            row_frames.append(pil_to_qpixmap(cell))
        out[name] = row_frames
    return out


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
    return True


class PetWindow(QWidget):
    def __init__(
        self,
        pet_name: str,
        frames: dict[str, list[QPixmap]],
        state_file: Path,
        claude_pid_file: Path,
        position_index: int,
    ):
        super().__init__()
        self.setWindowTitle(f"clawdex: {pet_name}")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        self.frames = frames
        self.state_file = state_file
        self.claude_pid_file = claude_pid_file
        self.current_state = "idle"
        self.frame_idx = 0
        self.transient_remaining = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(self)
        self.label.setAttribute(Qt.WA_TranslucentBackground)
        layout.addWidget(self.label)

        max_w = max(p.width() for ps in frames.values() for p in ps)
        max_h = max(p.height() for ps in frames.values() for p in ps)
        self.resize(max_w, max_h)

        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - self.width() - 40 - position_index * (self.width() + 20)
        y = screen.bottom() - self.height() - 80
        self.move(max(screen.left(), x), y)

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.tick)
        # First impression: pet waves on appear; transient logic falls back to idle.
        self.set_state("waving")

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_state)
        self.poll_timer.start(250)
        self._last_state_mtime = 0.0

        self.parent_timer = QTimer(self)
        self.parent_timer.timeout.connect(self._check_parent_alive)
        self.parent_timer.start(3000)

        self._drag_offset: QPoint | None = None

    def set_state(self, state: str) -> None:
        if state not in STATES:
            return
        self.current_state = state
        self.frame_idx = 0
        spec = STATES[state]
        per_frame_ms = max(60, spec["duration"] // spec["frames"])
        self.anim_timer.start(per_frame_ms)
        self.transient_remaining = spec["frames"] * 2 if spec["transient"] else 0
        self._render()

    def _render(self) -> None:
        self.label.setPixmap(self.frames[self.current_state][self.frame_idx])

    def tick(self) -> None:
        spec = STATES[self.current_state]
        self.frame_idx = (self.frame_idx + 1) % spec["frames"]
        self._render()
        if spec["transient"]:
            self.transient_remaining -= 1
            if self.transient_remaining <= 0:
                if spec.get("exit_on_done"):
                    QApplication.instance().quit()
                else:
                    self.set_state("idle")

    def poll_state(self) -> None:
        try:
            st = self.state_file.stat()
        except FileNotFoundError:
            return
        if st.st_mtime == self._last_state_mtime:
            return
        self._last_state_mtime = st.st_mtime
        try:
            content = self.state_file.read_text().strip()
        except OSError:
            return
        if not content:
            return
        new_state = content
        if content.startswith("{"):
            try:
                new_state = json.loads(content).get("state", "idle")
            except json.JSONDecodeError:
                return
        if new_state in STATES and new_state != self.current_state:
            self.set_state(new_state)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.globalPos() - self.frameGeometry().topLeft()
        elif e.button() == Qt.RightButton:
            self._show_menu(e.globalPos())

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_offset is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag_offset)

    def mouseReleaseEvent(self, _e: QMouseEvent) -> None:
        self._drag_offset = None

    def mouseDoubleClickEvent(self, _e: QMouseEvent) -> None:
        self.set_state("waving")

    def _show_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        for name in STATES:
            menu.addAction(name).triggered.connect(
                lambda _=False, s=name: self.set_state(s)
            )
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(QApplication.instance().quit)
        menu.exec_(pos)

    def _check_parent_alive(self) -> None:
        """Wave goodbye and quit when the parent Claude Code process is gone.

        Handles ungraceful exits (terminal closed, Claude crashed) where the
        SessionEnd hook never fired. The pet plays the farewell animation
        before quitting so it never just blinks out of existence.
        """
        if self.current_state == "farewell":
            return
        if not self.claude_pid_file.exists():
            return
        try:
            pid = int(self.claude_pid_file.read_text().strip())
        except (ValueError, OSError):
            return
        if pid <= 0:
            return
        if not _pid_alive(pid):
            self.parent_timer.stop()
            self.set_state("farewell")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pet", required=True)
    ap.add_argument("--scale", type=float, default=0.5)
    ap.add_argument("--session", default="default")
    ap.add_argument("--position-index", type=int, default=0)
    args = ap.parse_args()

    pet_path = PETDEX_DIR / args.pet
    if not (pet_path / "spritesheet.webp").exists():
        print(
            f"clawdex: pet not found at {pet_path}.\n"
            f"  Install with: npx petdex install {args.pet}",
            file=sys.stderr,
        )
        return 1

    sess_dir = CLAWDEX_DIR / "sessions" / args.session
    sess_dir.mkdir(parents=True, exist_ok=True)
    state_file = sess_dir / "state"
    claude_pid_file = sess_dir / "claude_pid"
    if not state_file.exists():
        state_file.write_text("idle")

    app = QApplication(sys.argv[:1])
    frames = load_frames(pet_path, args.scale)
    w = PetWindow(args.pet, frames, state_file, claude_pid_file, args.position_index)
    w.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
