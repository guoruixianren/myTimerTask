# myTimerTask - System Tray Task Timer

**English** | **[中文](README.md)**

A cross-platform system tray application for **task reminders**, **task logging**, and **memory monitoring**. Written in Python, runs on Windows, Linux, and macOS.

## ✨ Features

### 📊 Memory Monitoring
- **Tray icon**: Displays memory usage percentage in large, clear text
  - 🟢 Green: < 80%
  - 🟠 Orange: 80% – 90%
  - 🔴 Red: > 90%
- **Floating widget**: An always-on-top, 70% transparent square at the bottom-left of the screen, showing real-time memory percentage with the same color coding
- **High memory process killer**: When memory exceeds 94%, automatically kills processes in priority order:
  `Chrome → Edge → Java → VSCode (code)`
  Waits 5 seconds after each kill; continues killing if memory remains above 90%

### ⏱ 10-Minute Tasks (Left-click the floating icon)
- Opens a task panel with 5 single-line text fields
- Each field is approximately 20 Chinese characters wide
- Title shows `当前10分钟任务:[yyyy:MM:dd hh:mm.ss]`
- Editing any text restarts the 10-minute countdown
- When the countdown expires, the panel auto-pops up with 5 white/green alternating flashes

### ⏰ Hourly Tasks (Right-click the floating icon)
- Opens a task panel with 20 entries (initially shows 5, scroll to see more)
- Title shows `当前小时任务:[yyyy:MM:dd hh:mm.ss]`
- Counts down strictly to the next whole hour based on system time
- Auto-pops up at every hour mark with 5 white/green alternating flashes

### ✅ Task Management
- Each task has a ✓ button; click to mark as complete
- Completed tasks are removed from the list; remaining tasks shift up; last row becomes empty
- Completed entries are logged to `10分钟任务日志.md` in the format: `yyyy:MM:dd hh:mm.ss Finish Task: task content`

### 🔒 Auto-Close
- Task panels close automatically after 15 seconds of inactivity

## 📋 Requirements

- Python 3.10+
- Runs on **Windows**, **Linux**, and **macOS**

## 🚀 Installation & Usage

### Install Dependencies

```bash
pip install -r requirements.txt
```

> **Linux note**: The system tray icon requires `libappindicator3` or a compatible indicator service. If the tray icon is unavailable, the floating widget still works.

### Run

```bash
python3 systray_task.py
```

## 📁 Files Generated at Runtime

| File | Description |
|------|-------------|
| `tasks.json` | Persists task list contents between sessions |
| `10分钟任务日志.md` | Log of all completed tasks with timestamps |

## 📝 Log Format Example

```
2024:03:28 14:30.00 Finish Task: Write design document
```

## 🛠 Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.10+ |
| GUI | tkinter (standard library) |
| System Tray | pystray + Pillow |
| System Info | psutil |

## 📄 License

This project is open-sourced under the [MIT License](LICENSE).
