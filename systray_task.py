#!/usr/bin/env python3
"""
SysTray Task Timer
A cross-platform system tray application for task reminders and memory monitoring.

Features:
- System tray icon showing memory % with color coding
- Floating always-on-top widget (bottom-left, 70% transparent)
- Left-click: 10-minute task panel (5 tasks, auto-popup + flash at 10 min)
- Right-click: hourly task panel (20 tasks, auto-popup + flash at each whole hour)
- Task completion logging to markdown file
- Auto process killing when memory exceeds 94%
- 15-second auto-close on inactivity

Usage: python3 systray_task.py
"""

import os
import sys
import time
import threading
import datetime
import json

import psutil

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False
    print("Warning: pystray/Pillow not installed. System tray icon disabled.")
    print("  Install with: pip install pystray pillow")

import tkinter as tk
from tkinter import ttk

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MEM_ORANGE_THRESHOLD = 80   # >= 80%: orange
MEM_RED_THRESHOLD = 90      # >= 90%: red
KILL_THRESHOLD = 94         # >= 94%: kill processes

# Processes to kill in priority order (case-insensitive substring match)
KILL_PROCESS_ORDER = ["chrome", "msedge", "edge", "java", "code"]
KILL_WAIT_SECONDS = 5       # Wait this many seconds between kills

AUTO_CLOSE_SECONDS = 15     # Auto-close task panel after this many idle seconds
TEN_MIN_SECONDS = 10 * 60   # 10-minute timer in seconds
MEMORY_POLL_SECONDS = 5     # How often to check memory

LOG_FILE = "10分钟任务日志.md"
TASKS_FILE = "tasks.json"

NUM_10MIN_TASKS = 5
NUM_HOURLY_TASKS = 20

# Colors
COLOR_GREEN = "#00cc00"
COLOR_ORANGE = "#ff8800"
COLOR_RED = "#ff2200"
COLOR_WHITE = "#ffffff"
COLOR_BG = "#1e1e1e"

ICON_SIZE = 64        # System tray icon size in pixels
TRAY_ICON_FONT_SIZE = 20  # Font size for memory % text inside tray icon

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def get_mem_color(percent: float) -> str:
    """Return hex color string based on memory percentage."""
    if percent < MEM_ORANGE_THRESHOLD:
        return COLOR_GREEN
    elif percent < MEM_RED_THRESHOLD:
        return COLOR_ORANGE
    else:
        return COLOR_RED


def now_str() -> str:
    """Return current datetime formatted as YYYY:MM:DD HH:MM.SS"""
    return datetime.datetime.now().strftime("%Y:%m:%d %H:%M.%S")


def next_whole_hour() -> datetime.datetime:
    """Return the next whole hour as a datetime."""
    now = datetime.datetime.now()
    return (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)


def load_tasks() -> dict:
    """Load tasks from JSON file. Returns dict with '10min' and 'hourly' lists."""
    default = {
        "10min": [""] * NUM_10MIN_TASKS,
        "hourly": [""] * NUM_HOURLY_TASKS,
    }
    try:
        if os.path.exists(TASKS_FILE):
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Ensure correct lengths
            tasks_10min = data.get("10min", [])
            tasks_hourly = data.get("hourly", [])
            while len(tasks_10min) < NUM_10MIN_TASKS:
                tasks_10min.append("")
            while len(tasks_hourly) < NUM_HOURLY_TASKS:
                tasks_hourly.append("")
            return {
                "10min": tasks_10min[:NUM_10MIN_TASKS],
                "hourly": tasks_hourly[:NUM_HOURLY_TASKS],
            }
    except Exception as e:
        print(f"Warning: could not load tasks: {e}")
    return default


def save_tasks(tasks: dict) -> None:
    """Persist tasks dict to JSON file."""
    try:
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Warning: could not save tasks: {e}")


def log_completed_task(task_text: str) -> None:
    """Append a completed task entry to the markdown log file."""
    entry = f"{now_str()} Finish Task: {task_text}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        print(f"Warning: could not write to log file: {e}")


# ---------------------------------------------------------------------------
# Memory Monitor (background thread)
# ---------------------------------------------------------------------------


class MemoryMonitor:
    """Polls memory usage periodically and triggers callbacks."""

    def __init__(self, on_update):
        self._on_update = on_update
        self._running = False
        self._thread = None
        self._last_kill_time = 0.0

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="MemMonitor")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        while self._running:
            try:
                mem = psutil.virtual_memory()
                percent = mem.percent
                self._on_update(percent)

                if percent >= KILL_THRESHOLD:
                    now = time.monotonic()
                    if now - self._last_kill_time >= KILL_WAIT_SECONDS:
                        killed = self._kill_next_process(percent)
                        if killed:
                            self._last_kill_time = now
            except Exception as e:
                print(f"MemoryMonitor error: {e}")
            time.sleep(MEMORY_POLL_SECONDS)

    def _kill_next_process(self, mem_percent: float) -> bool:
        """Kill the next process in KILL_PROCESS_ORDER. Returns True if killed."""
        # Find running processes that match the kill list in order
        running_map: dict[str, psutil.Process] = {}
        try:
            for proc in psutil.process_iter(["name", "pid"]):
                pname = (proc.info["name"] or "").lower()
                for kill_name in KILL_PROCESS_ORDER:
                    if kill_name in pname and kill_name not in running_map:
                        running_map[kill_name] = proc
        except Exception:
            pass

        # Kill the first in the priority order that is running
        for kill_name in KILL_PROCESS_ORDER:
            if kill_name in running_map:
                proc = running_map[kill_name]
                try:
                    proc.kill()
                    print(f"[MemKill] Killed '{kill_name}' (pid={proc.pid}) at {mem_percent:.1f}% memory")
                    return True
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    print(f"[MemKill] Could not kill '{kill_name}': {e}")
        return False


# ---------------------------------------------------------------------------
# System Tray Icon
# ---------------------------------------------------------------------------


def _make_tray_image(percent: float) -> "Image.Image":
    """Create a PIL image for the tray icon with memory percentage text."""
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    color_hex = get_mem_color(percent)
    r = int(color_hex[1:3], 16)
    g = int(color_hex[3:5], 16)
    b = int(color_hex[5:7], 16)

    # Draw filled rounded rectangle as background
    margin = 2
    draw.rounded_rectangle(
        [margin, margin, ICON_SIZE - margin, ICON_SIZE - margin],
        radius=10,
        fill=(r, g, b, 230),
    )

    # Try to load a bold font; fall back to default
    text = f"{int(percent)}%"
    font = None
    candidate_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidate_fonts:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, TRAY_ICON_FONT_SIZE)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    # Center the text
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (ICON_SIZE - tw) / 2 - bbox[0]
    ty = (ICON_SIZE - th) / 2 - bbox[1]
    draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)

    return img


# ---------------------------------------------------------------------------
# Floating Widget (always-on-top transparent overlay)
# ---------------------------------------------------------------------------


class FloatingWidget:
    """
    A small square floating window at the bottom-left of the screen.
    70% transparent (alpha=0.3), always on top, shows memory %.
    Left-click → 10-min task panel; right-click → hourly task panel.
    Draggable with left-button drag.
    """

    WIDGET_SIZE = 70

    def __init__(self, root: tk.Tk, app: "App"):
        self._app = app
        self._root = root

        self._win = tk.Toplevel(root)
        self._win.overrideredirect(True)
        self._win.wm_attributes("-topmost", True)
        # 70% transparent = alpha 0.3
        try:
            self._win.wm_attributes("-alpha", 0.3)
        except tk.TclError:
            pass  # Not all platforms support alpha

        # Position bottom-left
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = 20
        y = sh - self.WIDGET_SIZE - 80
        self._win.geometry(f"{self.WIDGET_SIZE}x{self.WIDGET_SIZE}+{x}+{y}")
        self._win.configure(bg="black")

        self._label = tk.Label(
            self._win,
            text="0%",
            font=("Arial", 16, "bold"),
            fg=COLOR_GREEN,
            bg="black",
            cursor="hand2",
        )
        self._label.place(relx=0.5, rely=0.5, anchor="center")

        # Drag state
        self._drag_x = 0
        self._drag_y = 0
        self._win_x = x
        self._win_y = y
        self._dragging = False
        self._press_x = 0
        self._press_y = 0

        self._label.bind("<ButtonPress-1>", self._on_press)
        self._label.bind("<B1-Motion>", self._on_drag)
        self._label.bind("<ButtonRelease-1>", self._on_release)
        self._label.bind("<Button-3>", self._on_right_click)
        self._win.bind("<ButtonPress-1>", self._on_press)
        self._win.bind("<B1-Motion>", self._on_drag)
        self._win.bind("<ButtonRelease-1>", self._on_release)
        self._win.bind("<Button-3>", self._on_right_click)

    def _on_press(self, event):
        self._press_x = event.x_root
        self._press_y = event.y_root
        self._win_x = self._win.winfo_x()
        self._win_y = self._win.winfo_y()
        self._dragging = False

    def _on_drag(self, event):
        dx = event.x_root - self._press_x
        dy = event.y_root - self._press_y
        if abs(dx) > 4 or abs(dy) > 4:
            self._dragging = True
        if self._dragging:
            nx = self._win_x + dx
            ny = self._win_y + dy
            self._win.geometry(f"+{nx}+{ny}")

    def _on_release(self, event):
        if not self._dragging:
            self._app.show_10min_panel()

    def _on_right_click(self, event):
        self._app.show_hourly_panel()

    def update_memory(self, percent: float) -> None:
        color = get_mem_color(percent)
        self._label.config(text=f"{int(percent)}%", fg=color)

    def get_position(self) -> tuple[int, int]:
        """Return (x, y) of the floating widget for panel positioning."""
        return self._win.winfo_x(), self._win.winfo_y()

    def exists(self) -> bool:
        try:
            return bool(self._win.winfo_exists())
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Task Panel
# ---------------------------------------------------------------------------


class TaskPanel:
    """
    A Toplevel window for managing tasks (10-min or hourly).

    - Shows a title with the current time.
    - Shows task text entries with a ✓ button per row.
    - Auto-closes after AUTO_CLOSE_SECONDS of inactivity.
    - Can flash (white/green) on timer fire.
    """

    def __init__(self, root: tk.Tk, app: "App", mode: str):
        """
        mode: '10min' or 'hourly'
        """
        self._root = root
        self._app = app
        self._mode = mode
        self._last_activity = time.monotonic()
        self._destroyed = False

        self._win = tk.Toplevel(root)
        self._win.wm_attributes("-topmost", True)
        self._win.protocol("WM_DELETE_WINDOW", self._on_close)

        num_tasks = NUM_10MIN_TASKS if mode == "10min" else NUM_HOURLY_TASKS

        # Load current tasks
        tasks = self._app.get_tasks(mode)

        # Window title
        if mode == "10min":
            self._win.title("10分钟任务")
        else:
            self._win.title("小时任务")

        # -- Build UI --
        outer = tk.Frame(self._win, bg=COLOR_BG, padx=8, pady=8)
        outer.pack(fill="both", expand=True)

        # Title label (updated periodically)
        self._title_var = tk.StringVar()
        self._update_title()
        title_lbl = tk.Label(
            outer,
            textvariable=self._title_var,
            font=("Arial", 10, "bold"),
            fg=COLOR_GREEN,
            bg=COLOR_BG,
            anchor="w",
        )
        title_lbl.pack(fill="x", pady=(0, 6))

        # Scrollable frame for tasks (needed for hourly to show 20 rows)
        task_frame_container = tk.Frame(outer, bg=COLOR_BG)
        task_frame_container.pack(fill="both", expand=True)

        if mode == "hourly":
            canvas = tk.Canvas(task_frame_container, bg=COLOR_BG, highlightthickness=0)
            scrollbar = ttk.Scrollbar(task_frame_container, orient="vertical", command=canvas.yview)
            self._scroll_frame = tk.Frame(canvas, bg=COLOR_BG)
            self._scroll_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
            )
            canvas.create_window((0, 0), window=self._scroll_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)
            task_container = self._scroll_frame
        else:
            task_container = task_frame_container

        # Task rows
        self._task_vars: list[tk.StringVar] = []
        self._entries: list[tk.Entry] = []

        for i in range(num_tasks):
            row = tk.Frame(task_container, bg=COLOR_BG)
            row.pack(fill="x", pady=1)

            var = tk.StringVar(value=tasks[i] if i < len(tasks) else "")
            self._task_vars.append(var)

            entry = tk.Entry(
                row,
                textvariable=var,
                width=22,
                font=("Arial", 10),
                bg="#2d2d2d",
                fg="#ffffff",
                insertbackground="#ffffff",
                relief="flat",
                bd=2,
            )
            entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
            entry.bind("<Key>", lambda e, idx=i: self._on_task_modified(idx))
            entry.bind("<Button-1>", self._on_activity)
            self._entries.append(entry)

            btn = tk.Button(
                row,
                text="✓",
                width=2,
                font=("Arial", 10, "bold"),
                fg=COLOR_GREEN,
                bg="#333333",
                relief="flat",
                cursor="hand2",
                command=lambda idx=i: self._complete_task(idx),
            )
            btn.pack(side="left")

        # Bind activity on the window itself
        self._win.bind("<Motion>", self._on_activity)
        self._win.bind("<Button>", self._on_activity)
        self._win.bind("<Key>", self._on_activity)

        # Size and position
        panel_w = 450
        panel_h = 220 if mode == "10min" else 380

        # Place to the right of the floating widget
        fw_x, fw_y = self._app.get_floating_widget_pos()
        x = fw_x + 80
        y = fw_y - panel_h + FloatingWidget.WIDGET_SIZE
        # Clamp to screen
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = min(x, sw - panel_w - 10)
        y = max(y, 10)
        self._win.geometry(f"{panel_w}x{panel_h}+{x}+{y}")

        # Start auto-close check
        self._schedule_auto_close()

        # Update title every second
        self._schedule_title_update()

    # -- Title --

    def _update_title(self) -> None:
        now = datetime.datetime.now()
        time_str = now.strftime("%Y:%m:%d %H:%M.%S")
        if self._mode == "10min":
            remaining = self._app.get_10min_remaining()
            mm = remaining // 60
            ss = remaining % 60
            self._title_var.set(f"当前10分钟任务:[{time_str}]  剩余{mm:02d}:{ss:02d}")
        else:
            nh = next_whole_hour()
            delta = nh - now
            total = int(delta.total_seconds())
            mm = total // 60
            ss = total % 60
            self._title_var.set(f"当前小时任务:[{time_str}]  至整点{mm:02d}:{ss:02d}")

    def _schedule_title_update(self) -> None:
        if self._destroyed or not self._win.winfo_exists():
            return
        self._update_title()
        self._win.after(1000, self._schedule_title_update)

    # -- Activity --

    def _on_activity(self, event=None) -> None:
        self._last_activity = time.monotonic()

    def _on_task_modified(self, idx: int) -> None:
        """Called when a task entry key is pressed."""
        self._on_activity()
        # Save tasks; restart 10-min timer if this is the 10-min panel
        self._save_tasks()
        if self._mode == "10min":
            self._app.restart_10min_timer()

    def _save_tasks(self) -> None:
        tasks = [v.get() for v in self._task_vars]
        self._app.set_tasks(self._mode, tasks)

    # -- Task completion --

    def _complete_task(self, idx: int) -> None:
        self._on_activity()
        task_text = self._task_vars[idx].get().strip()
        if not task_text:
            return

        log_completed_task(task_text)

        # Shift remaining tasks up, append empty at end
        vals = [v.get() for v in self._task_vars]
        vals.pop(idx)
        vals.append("")
        for i, var in enumerate(self._task_vars):
            var.set(vals[i])

        self._save_tasks()

    # -- Auto-close --

    def _schedule_auto_close(self) -> None:
        if self._destroyed or not self._win.winfo_exists():
            return
        elapsed = time.monotonic() - self._last_activity
        if elapsed >= AUTO_CLOSE_SECONDS:
            self._on_close()
        else:
            self._win.after(1000, self._schedule_auto_close)

    def _on_close(self) -> None:
        self._destroyed = True
        self._save_tasks()
        try:
            self._win.destroy()
        except Exception:
            pass
        self._app.on_panel_closed(self._mode)

    # -- Flash animation --

    def flash(self, cycles: int = 5) -> None:
        """Flash window background white/green alternately for `cycles` cycles."""
        steps = cycles * 2  # each cycle = 1 white + 1 green flash
        self._flash_step(steps)

    def _flash_step(self, remaining: int) -> None:
        if self._destroyed or not self._win.winfo_exists():
            return
        if remaining <= 0:
            # Restore normal background
            self._win.configure(bg=COLOR_BG)
            return
        color = COLOR_WHITE if remaining % 2 == 0 else COLOR_GREEN
        self._win.configure(bg=color)
        self._win.after(400, lambda: self._flash_step(remaining - 1))

    def lift(self) -> None:
        try:
            self._win.lift()
            self._win.focus_force()
            self._last_activity = time.monotonic()
        except Exception:
            pass

    def exists(self) -> bool:
        try:
            return bool(self._win.winfo_exists()) and not self._destroyed
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------


class App:
    """Orchestrates all components."""

    def __init__(self):
        # Root window (hidden)
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.title("SysTray Task Timer")

        # Task storage
        self._tasks = load_tasks()

        # Panels (None when closed)
        self._panel_10min: TaskPanel | None = None
        self._panel_hourly: TaskPanel | None = None

        # 10-min timer state
        self._10min_deadline = time.monotonic() + TEN_MIN_SECONDS

        # Memory
        self._mem_percent = 0.0
        self._mem_monitor = MemoryMonitor(on_update=self._on_mem_update)

        # Floating widget
        self._floating = FloatingWidget(self._root, self)

        # System tray
        self._tray_icon = None
        if HAS_PYSTRAY:
            self._setup_tray()

        # Start memory monitoring
        self._mem_monitor.start()

        # Schedule timers via tkinter.after (runs in main thread)
        self._schedule_10min_check()
        self._schedule_hourly_check()

    # -- Tray icon --

    def _setup_tray(self) -> None:
        img = _make_tray_image(0)
        menu = pystray.Menu(
            pystray.MenuItem("显示10分钟任务", lambda: self._root.after(0, self.show_10min_panel)),
            pystray.MenuItem("显示小时任务", lambda: self._root.after(0, self.show_hourly_panel)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: self._root.after(0, self.quit)),
        )
        self._tray_icon = pystray.Icon("TaskTimer", img, "Memory: 0%", menu)
        t = threading.Thread(target=self._tray_icon.run, daemon=True, name="TrayIcon")
        t.start()

    def _update_tray(self, percent: float) -> None:
        if self._tray_icon and HAS_PYSTRAY:
            try:
                self._tray_icon.icon = _make_tray_image(percent)
                self._tray_icon.title = f"Memory: {percent:.1f}%"
            except Exception as e:
                print(f"Tray update error: {e}")

    # -- Memory callbacks --

    def _on_mem_update(self, percent: float) -> None:
        """Called from background thread."""
        self._mem_percent = percent
        # Schedule UI update on main thread
        try:
            self._root.after(0, lambda: self._apply_mem_update(percent))
        except Exception:
            pass

    def _apply_mem_update(self, percent: float) -> None:
        if self._floating.exists():
            self._floating.update_memory(percent)
        self._update_tray(percent)

    # -- 10-minute timer --

    def restart_10min_timer(self) -> None:
        """Reset the 10-minute countdown (called on task modification)."""
        self._10min_deadline = time.monotonic() + TEN_MIN_SECONDS

    def get_10min_remaining(self) -> int:
        """Return seconds remaining until the 10-min timer fires."""
        remaining = self._10min_deadline - time.monotonic()
        return max(0, int(remaining))

    def _schedule_10min_check(self) -> None:
        self._root.after(1000, self._check_10min_timer)

    def _check_10min_timer(self) -> None:
        if time.monotonic() >= self._10min_deadline:
            # Reset timer first to avoid double-firing
            self._10min_deadline = time.monotonic() + TEN_MIN_SECONDS
            self._on_10min_fire()
        self._root.after(1000, self._check_10min_timer)

    def _on_10min_fire(self) -> None:
        self.show_10min_panel()
        if self._panel_10min and self._panel_10min.exists():
            self._panel_10min.flash()

    # -- Hourly timer --

    def _schedule_hourly_check(self) -> None:
        self._root.after(1000, self._check_hourly_timer)

    def _check_hourly_timer(self) -> None:
        now = datetime.datetime.now()
        # Fire at exactly HH:00:00 (within 1-second window)
        if now.minute == 0 and now.second == 0:
            self._on_hourly_fire()
            # Wait 2 seconds before scheduling again to avoid double-fire
            self._root.after(2000, self._schedule_hourly_check)
        else:
            self._root.after(1000, self._check_hourly_timer)

    def _on_hourly_fire(self) -> None:
        self.show_hourly_panel()
        if self._panel_hourly and self._panel_hourly.exists():
            self._panel_hourly.flash()

    # -- Panel management --

    def show_10min_panel(self) -> None:
        if self._panel_10min and self._panel_10min.exists():
            self._panel_10min.lift()
        else:
            self._panel_10min = TaskPanel(self._root, self, "10min")

    def show_hourly_panel(self) -> None:
        if self._panel_hourly and self._panel_hourly.exists():
            self._panel_hourly.lift()
        else:
            self._panel_hourly = TaskPanel(self._root, self, "hourly")

    def on_panel_closed(self, mode: str) -> None:
        if mode == "10min":
            self._panel_10min = None
        else:
            self._panel_hourly = None

    # -- Task data --

    def get_tasks(self, mode: str) -> list[str]:
        return list(self._tasks[mode])

    def set_tasks(self, mode: str, tasks: list[str]) -> None:
        self._tasks[mode] = list(tasks)
        save_tasks(self._tasks)

    # -- Floating widget position --

    def get_floating_widget_pos(self) -> tuple[int, int]:
        return self._floating.get_position()

    # -- Quit --

    def quit(self) -> None:
        save_tasks(self._tasks)
        self._mem_monitor.stop()
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        try:
            self._root.quit()
            self._root.destroy()
        except Exception:
            pass

    def run(self) -> None:
        self._root.mainloop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    app = App()
    app.run()


if __name__ == "__main__":
    main()
