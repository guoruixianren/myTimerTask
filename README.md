# myTimerTask

A cross-platform system tray application written in Python for task reminders and memory monitoring.

## Features

- **System tray icon**: Displays memory percentage with large, clear text
  - Green (< 80%), Orange (80–90%), Red (> 90%)
- **Floating widget**: Always-on-top, 70% transparent square at the bottom-left of the screen, shows memory %
- **10-minute task panel** (left-click the floating widget):
  - 5 single-line task entries
  - Countdown timer resets on every task edit
  - Auto-pops up after 10 minutes with a white/green flash
- **Hourly task panel** (right-click the floating widget):
  - 20 task entries (initially shows 5, scroll to see more)
  - Countdown strictly to the next whole hour
  - Auto-pops up at every hour mark with a white/green flash
- **Task completion**: Click ✓ to complete a task; it is removed, remaining tasks shift up, and the entry is logged to `10分钟任务日志.md`
- **Auto-close**: Task panels close automatically after 15 seconds of inactivity
- **High memory process killer**: When memory exceeds 94%, kills processes in order: `chrome → edge → java → vscode (code)`, waiting 5 s between each kill

## Requirements

- Python 3.10+
- Works on **Windows**, **Linux**, and **macOS**

## Installation

```bash
pip install -r requirements.txt
```

> **Linux note**: The system tray icon requires `libappindicator3` or a compatible indicator service. If the tray icon is unavailable, the floating widget still works.

## Usage

```bash
python3 systray_task.py
```

## Files generated at runtime

| File | Description |
|------|-------------|
| `tasks.json` | Persists task list contents between sessions |
| `10分钟任务日志.md` | Log of all completed tasks with timestamps |

## Log format

```
2024:03:28 14:30.00 Finish Task: Write design document
```