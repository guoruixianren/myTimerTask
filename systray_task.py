#!/usr/bin/env python3
"""
SysTray 任务定时器
跨平台系统托盘应用程序，用于任务定时提醒、任务记录和内存监控。

功能：
- 系统托盘图标：大字体显示内存百分比，颜色分级（绿色<80%，橙色80-90%，红色>90%）
- 悬浮窗口：始终置顶的半透明（70%透明度）小方块，位于屏幕左下角，显示内存百分比
- 左键点击悬浮窗口：弹出10分钟任务面板（5条任务），文本修改后重新倒计时10分钟
- 右键点击悬浮窗口：弹出小时任务面板（20条任务，初始显示5条，可滚动查看），整点倒计时
- 任务完成后记入Markdown日志文件
- 内存超过94%时自动按优先级杀进程，每杀一次等5秒，超过90%继续杀
- 弹窗15秒无操作自动关闭

用法: python3 systray_task.py
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
    print("警告: pystray/Pillow 未安装，系统托盘图标功能已禁用。")
    print("  安装命令: pip install pystray pillow")

import tkinter as tk
from tkinter import ttk

# ---------------------------------------------------------------------------
# 获取脚本所在目录，确保数据文件存放在固定位置（而非依赖当前工作目录）
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------

MEM_ORANGE_THRESHOLD = 80   # 内存占用 >= 80%：橙色警告
MEM_RED_THRESHOLD = 90      # 内存占用 >= 90%：红色警告
KILL_THRESHOLD = 94         # 内存占用 >= 94%：开始杀进程
KILL_CONTINUE_THRESHOLD = 90  # 杀进程后若内存仍 >= 90%，则继续杀下一个

# 待杀进程的优先级列表（按序匹配进程名，不区分大小写）
KILL_PROCESS_ORDER = ["chrome", "msedge", "edge", "java", "code"]
KILL_WAIT_SECONDS = 5       # 每次杀进程后等待的秒数

AUTO_CLOSE_SECONDS = 15     # 弹窗空闲自动关闭时间（秒）
TEN_MIN_SECONDS = 10 * 60   # 10分钟定时器（秒）
MEMORY_POLL_SECONDS = 5     # 内存轮询间隔（秒）

# 数据文件路径（统一存放在脚本目录下）
LOG_FILE = os.path.join(_SCRIPT_DIR, "10分钟任务日志.md")
TASKS_FILE = os.path.join(_SCRIPT_DIR, "tasks.json")

NUM_10MIN_TASKS = 5         # 10分钟任务面板的任务条数
NUM_HOURLY_TASKS = 20       # 小时任务面板的任务条数

# 颜色常量
COLOR_GREEN = "#00cc00"     # 内存正常（<80%）
COLOR_ORANGE = "#ff8800"    # 内存警告（80%-90%）
COLOR_RED = "#ff2200"       # 内存危险（>90%）
COLOR_WHITE = "#ffffff"     # 闪烁用白色
COLOR_BG = "#1e1e1e"        # 面板背景色

ICON_SIZE = 64              # 系统托盘图标尺寸（像素）
TRAY_ICON_FONT_SIZE = 20    # 托盘图标内存百分比字体大小

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def get_mem_color(percent: float) -> str:
    """根据内存百分比返回对应的十六进制颜色字符串。
    <80% 绿色，80%-90% 橙色，>=90% 红色。"""
    if percent < MEM_ORANGE_THRESHOLD:
        return COLOR_GREEN
    elif percent < MEM_RED_THRESHOLD:
        return COLOR_ORANGE
    else:
        return COLOR_RED


def now_str() -> str:
    """返回当前时间的格式化字符串，格式为 YYYY:MM:DD HH:MM.SS"""
    return datetime.datetime.now().strftime("%Y:%m:%d %H:%M.%S")


def next_whole_hour() -> datetime.datetime:
    """计算并返回下一个整点小时的 datetime 对象。"""
    now = datetime.datetime.now()
    return (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)


def load_tasks() -> dict:
    """从 JSON 文件加载任务列表。返回包含 '10min' 和 'hourly' 两个列表的字典。
    如果文件不存在或读取失败，返回默认空列表。"""
    default = {
        "10min": [""] * NUM_10MIN_TASKS,
        "hourly": [""] * NUM_HOURLY_TASKS,
    }
    try:
        if os.path.exists(TASKS_FILE):
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 确保列表长度符合预设
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
        print(f"警告: 无法加载任务文件: {e}")
    return default


def save_tasks(tasks: dict) -> None:
    """将任务字典持久化保存到 JSON 文件。"""
    try:
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"警告: 无法保存任务文件: {e}")


def log_completed_task(task_text: str) -> None:
    """将已完成的任务追加写入 Markdown 日志文件。
    格式: YYYY:MM:DD HH:MM.SS Finish Task: 任务内容"""
    entry = f"{now_str()} Finish Task: {task_text}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        print(f"警告: 无法写入日志文件: {e}")


# ---------------------------------------------------------------------------
# 内存监控（后台线程）
# ---------------------------------------------------------------------------


class MemoryMonitor:
    """周期性轮询内存使用率，触发回调更新UI，并在内存过高时自动杀进程。

    杀进程逻辑（需求3.2）：
    - 内存 >= 94% 时开始杀进程
    - 按优先级列表顺序杀: chrome → edge → java → vscode(code)
    - 每杀一个进程后等待5秒
    - 等待后若内存仍 >= 90%，继续按列表顺序杀下一个
    """

    def __init__(self, on_update):
        self._on_update = on_update  # 内存更新回调函数
        self._running = False
        self._thread = None

    def start(self) -> None:
        """启动内存监控后台线程。"""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="MemMonitor")
        self._thread.start()

    def stop(self) -> None:
        """停止内存监控。"""
        self._running = False

    def _run(self) -> None:
        """后台线程主循环：定期轮询内存并触发回调。"""
        while self._running:
            try:
                mem = psutil.virtual_memory()
                percent = mem.percent
                self._on_update(percent)

                # 内存超过94%阈值时，启动杀进程流程
                if percent >= KILL_THRESHOLD:
                    self._kill_process_chain()
            except Exception as e:
                print(f"内存监控异常: {e}")
            time.sleep(MEMORY_POLL_SECONDS)

    def _kill_process_chain(self) -> None:
        """按优先级列表依次杀进程，每杀一个等5秒后重新检测内存。
        若内存仍 >= 90% 则继续杀下一个，直到列表耗尽或内存降至90%以下。"""
        for kill_name in KILL_PROCESS_ORDER:
            if not self._running:
                return
            # 查找匹配该名称的所有进程
            killed_any = self._kill_processes_by_name(kill_name)
            if killed_any:
                # 杀完一组进程后等待5秒让系统回收内存
                time.sleep(KILL_WAIT_SECONDS)
                # 重新检测内存，若已降到90%以下则停止杀进程
                current_mem = psutil.virtual_memory().percent
                self._on_update(current_mem)
                if current_mem < KILL_CONTINUE_THRESHOLD:
                    return

    def _kill_processes_by_name(self, kill_name: str) -> bool:
        """杀掉所有进程名包含指定关键字的进程。
        返回是否成功杀掉了至少一个进程。"""
        killed = False
        try:
            for proc in psutil.process_iter(["name", "pid"]):
                pname = (proc.info["name"] or "").lower()
                if kill_name in pname:
                    try:
                        proc.kill()
                        print(f"[内存杀进程] 已终止 '{pname}' (pid={proc.pid}), "
                              f"匹配关键字='{kill_name}'")
                        killed = True
                    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                        print(f"[内存杀进程] 无法终止 '{pname}': {e}")
        except Exception as e:
            print(f"[内存杀进程] 枚举进程异常: {e}")
        return killed


# ---------------------------------------------------------------------------
# 系统托盘图标
# ---------------------------------------------------------------------------


def _make_tray_image(percent: float) -> "Image.Image":
    """生成系统托盘图标的 PIL 图片，图标上显示内存百分比文字。
    背景色根据内存占比分级显示（绿/橙/红）。"""
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 根据内存百分比确定颜色
    color_hex = get_mem_color(percent)
    r = int(color_hex[1:3], 16)
    g = int(color_hex[3:5], 16)
    b = int(color_hex[5:7], 16)

    # 绘制圆角矩形背景
    margin = 2
    draw.rounded_rectangle(
        [margin, margin, ICON_SIZE - margin, ICON_SIZE - margin],
        radius=10,
        fill=(r, g, b, 230),
    )

    # 尝试加载系统字体，失败则使用默认字体
    text = f"{int(percent)}%"
    font = None
    candidate_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",       # Linux
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", # Linux
        "/System/Library/Fonts/Helvetica.ttc",                          # macOS
        "C:/Windows/Fonts/arialbd.ttf",                                 # Windows
        "C:/Windows/Fonts/arial.ttf",                                   # Windows 备选
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

    # 居中绘制文字
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (ICON_SIZE - tw) / 2 - bbox[0]
    ty = (ICON_SIZE - th) / 2 - bbox[1]
    draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)

    return img


# ---------------------------------------------------------------------------
# 悬浮窗口（始终置顶的半透明悬浮图标）
# ---------------------------------------------------------------------------


class FloatingWidget:
    """屏幕左下角的小正方形悬浮窗口，70%透明度，始终置顶。
    显示内存百分比，颜色分级与托盘图标一致。
    - 左键点击：弹出10分钟任务面板
    - 右键点击：弹出小时任务面板
    - 支持拖拽移动
    """

    WIDGET_SIZE = 70  # 悬浮窗口边长（像素）

    def __init__(self, root: tk.Tk, app: "App"):
        self._app = app
        self._root = root

        self._win = tk.Toplevel(root)
        self._win.overrideredirect(True)    # 去掉窗口边框
        self._win.wm_attributes("-topmost", True)  # 始终置顶
        # 设置70%透明度（alpha=0.3表示30%不透明，即70%透明）
        try:
            self._win.wm_attributes("-alpha", 0.3)
        except tk.TclError:
            pass  # 部分平台不支持透明度设置

        # 定位到屏幕左下角
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = 20
        y = sh - self.WIDGET_SIZE - 80
        self._win.geometry(f"{self.WIDGET_SIZE}x{self.WIDGET_SIZE}+{x}+{y}")
        self._win.configure(bg="black")

        # 内存百分比显示标签
        self._label = tk.Label(
            self._win,
            text="0%",
            font=("Arial", 16, "bold"),
            fg=COLOR_GREEN,
            bg="black",
            cursor="hand2",
        )
        self._label.place(relx=0.5, rely=0.5, anchor="center")

        # 拖拽状态变量
        self._drag_x = 0
        self._drag_y = 0
        self._win_x = x
        self._win_y = y
        self._dragging = False
        self._press_x = 0
        self._press_y = 0

        # 绑定鼠标事件（标签和窗口都需要绑定以确保事件捕获）
        self._label.bind("<ButtonPress-1>", self._on_press)
        self._label.bind("<B1-Motion>", self._on_drag)
        self._label.bind("<ButtonRelease-1>", self._on_release)
        self._label.bind("<Button-3>", self._on_right_click)
        self._win.bind("<ButtonPress-1>", self._on_press)
        self._win.bind("<B1-Motion>", self._on_drag)
        self._win.bind("<ButtonRelease-1>", self._on_release)
        self._win.bind("<Button-3>", self._on_right_click)

    def _on_press(self, event):
        """鼠标左键按下：记录起始位置用于判断是点击还是拖拽。"""
        self._press_x = event.x_root
        self._press_y = event.y_root
        self._win_x = self._win.winfo_x()
        self._win_y = self._win.winfo_y()
        self._dragging = False

    def _on_drag(self, event):
        """鼠标拖拽：移动超过4像素后进入拖拽模式，更新窗口位置。"""
        dx = event.x_root - self._press_x
        dy = event.y_root - self._press_y
        if abs(dx) > 4 or abs(dy) > 4:
            self._dragging = True
        if self._dragging:
            nx = self._win_x + dx
            ny = self._win_y + dy
            self._win.geometry(f"+{nx}+{ny}")

    def _on_release(self, event):
        """鼠标左键释放：若未拖拽则视为点击，弹出10分钟任务面板。"""
        if not self._dragging:
            self._app.show_10min_panel()

    def _on_right_click(self, event):
        """鼠标右键点击：弹出小时任务面板。"""
        self._app.show_hourly_panel()

    def update_memory(self, percent: float) -> None:
        """更新悬浮窗口上显示的内存百分比和颜色。"""
        color = get_mem_color(percent)
        self._label.config(text=f"{int(percent)}%", fg=color)

    def get_position(self) -> tuple[int, int]:
        """返回悬浮窗口的当前坐标 (x, y)，用于定位任务面板。"""
        return self._win.winfo_x(), self._win.winfo_y()

    def exists(self) -> bool:
        """检查悬浮窗口是否仍然存在。"""
        try:
            return bool(self._win.winfo_exists())
        except Exception:
            return False


# ---------------------------------------------------------------------------
# 任务面板
# ---------------------------------------------------------------------------


class TaskPanel:
    """任务管理弹窗（10分钟任务 或 小时任务）。

    功能：
    - 标题栏显示当前时间和倒计时
    - 每行一个文本输入框和一个完成按钮（✓）
    - 点击 ✓ 完成任务：记录日志、上移其他任务、末行补空
    - 空闲超过15秒自动关闭窗口
    - 支持白绿交替闪烁动画（定时触发时使用）
    """

    def __init__(self, root: tk.Tk, app: "App", mode: str):
        """初始化任务面板。
        参数 mode: '10min'（10分钟任务）或 'hourly'（小时任务）
        """
        self._root = root
        self._app = app
        self._mode = mode
        self._last_activity = time.monotonic()  # 最近一次用户操作时间
        self._destroyed = False

        self._win = tk.Toplevel(root)
        self._win.wm_attributes("-topmost", True)  # 始终置顶
        self._win.protocol("WM_DELETE_WINDOW", self._on_close)

        num_tasks = NUM_10MIN_TASKS if mode == "10min" else NUM_HOURLY_TASKS

        # 加载当前已保存的任务
        tasks = self._app.get_tasks(mode)

        # 设置窗口标题
        if mode == "10min":
            self._win.title("10分钟任务")
        else:
            self._win.title("小时任务")

        # -- 构建界面 --
        outer = tk.Frame(self._win, bg=COLOR_BG, padx=8, pady=8)
        outer.pack(fill="both", expand=True)

        # 标题标签（每秒更新一次，显示当前时间和倒计时）
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

        # 任务行容器（小时任务需要滚动条以显示20条中超出5条可见区域的部分）
        task_frame_container = tk.Frame(outer, bg=COLOR_BG)
        task_frame_container.pack(fill="both", expand=True)

        if mode == "hourly":
            # 小时任务面板使用 Canvas + Scrollbar 实现滚动（初始显示5条，共20条）
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

        # 创建任务行（每行包含一个文本输入框和一个完成按钮）
        self._task_vars: list[tk.StringVar] = []
        self._entries: list[tk.Entry] = []

        for i in range(num_tasks):
            row = tk.Frame(task_container, bg=COLOR_BG)
            row.pack(fill="x", pady=1)

            var = tk.StringVar(value=tasks[i] if i < len(tasks) else "")
            self._task_vars.append(var)

            # 文本输入框（宽度约20个汉字）
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

            # 完成按钮（✓），点击后标记该行任务完成
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

        # 绑定窗口级的用户活动检测（用于自动关闭倒计时）
        self._win.bind("<Motion>", self._on_activity)
        self._win.bind("<Button>", self._on_activity)
        self._win.bind("<Key>", self._on_activity)

        # 计算窗口尺寸和位置
        panel_w = 450
        panel_h = 220 if mode == "10min" else 380

        # 面板出现在悬浮窗口的右侧
        fw_x, fw_y = self._app.get_floating_widget_pos()
        x = fw_x + 80
        y = fw_y - panel_h + FloatingWidget.WIDGET_SIZE
        # 限制窗口不超出屏幕边界
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = min(x, sw - panel_w - 10)
        y = max(y, 10)
        self._win.geometry(f"{panel_w}x{panel_h}+{x}+{y}")

        # 启动自动关闭检测
        self._schedule_auto_close()

        # 每秒刷新标题（时间和倒计时）
        self._schedule_title_update()

    # -- 标题更新 --

    def _update_title(self) -> None:
        """更新标题栏：显示当前时间和对应的倒计时。"""
        now = datetime.datetime.now()
        time_str = now.strftime("%Y:%m:%d %H:%M.%S")
        if self._mode == "10min":
            # 10分钟任务面板：显示距下次提醒的剩余时间
            remaining = self._app.get_10min_remaining()
            mm = remaining // 60
            ss = remaining % 60
            self._title_var.set(f"当前10分钟任务:[{time_str}]  剩余{mm:02d}:{ss:02d}")
        else:
            # 小时任务面板：显示距下一个整点的剩余时间
            nh = next_whole_hour()
            delta = nh - now
            total = int(delta.total_seconds())
            mm = total // 60
            ss = total % 60
            self._title_var.set(f"当前小时任务:[{time_str}]  至整点{mm:02d}:{ss:02d}")

    def _schedule_title_update(self) -> None:
        """每秒刷新一次标题栏。"""
        if self._destroyed or not self._win.winfo_exists():
            return
        self._update_title()
        self._win.after(1000, self._schedule_title_update)

    # -- 用户活动检测 --

    def _on_activity(self, event=None) -> None:
        """记录用户的最近一次操作时间（用于自动关闭计时）。"""
        self._last_activity = time.monotonic()

    def _on_task_modified(self, idx: int) -> None:
        """任务文本被修改时触发：重置活动计时，保存任务数据。
        若为10分钟面板，还会重启10分钟倒计时。"""
        self._on_activity()
        self._save_tasks()
        if self._mode == "10min":
            self._app.restart_10min_timer()

    def _save_tasks(self) -> None:
        """将当前面板中的任务文本保存到全局存储。"""
        tasks = [v.get() for v in self._task_vars]
        self._app.set_tasks(self._mode, tasks)

    # -- 任务完成处理 --

    def _complete_task(self, idx: int) -> None:
        """完成指定索引的任务：记录日志、删除该行、其余上移、末行补空。"""
        self._on_activity()
        task_text = self._task_vars[idx].get().strip()
        if not task_text:
            return

        # 将完成的任务写入日志文件
        log_completed_task(task_text)

        # 删除该行，剩余行上移，最后一行补空字符串
        vals = [v.get() for v in self._task_vars]
        vals.pop(idx)
        vals.append("")
        for i, var in enumerate(self._task_vars):
            var.set(vals[i])

        self._save_tasks()

    # -- 自动关闭 --

    def _schedule_auto_close(self) -> None:
        """每秒检查一次是否超过空闲时间限制，超过则关闭窗口。"""
        if self._destroyed or not self._win.winfo_exists():
            return
        elapsed = time.monotonic() - self._last_activity
        if elapsed >= AUTO_CLOSE_SECONDS:
            self._on_close()
        else:
            self._win.after(1000, self._schedule_auto_close)

    def _on_close(self) -> None:
        """关闭任务面板：保存数据、销毁窗口、通知应用层。"""
        self._destroyed = True
        self._save_tasks()
        try:
            self._win.destroy()
        except Exception:
            pass
        self._app.on_panel_closed(self._mode)

    # -- 闪烁动画 --

    def flash(self, cycles: int = 5) -> None:
        """白绿交替闪烁指定次数（每个周期 = 白色一次 + 绿色一次）。"""
        steps = cycles * 2  # 总闪烁步数
        self._flash_step(steps)

    def _flash_step(self, remaining: int) -> None:
        """执行一步闪烁动画：交替设置窗口背景为白色或绿色。"""
        if self._destroyed or not self._win.winfo_exists():
            return
        if remaining <= 0:
            # 闪烁结束，恢复正常背景色
            self._win.configure(bg=COLOR_BG)
            return
        color = COLOR_WHITE if remaining % 2 == 0 else COLOR_GREEN
        self._win.configure(bg=color)
        self._win.after(400, lambda: self._flash_step(remaining - 1))

    def lift(self) -> None:
        """将窗口提升到最前面并获取焦点。"""
        try:
            self._win.lift()
            self._win.focus_force()
            self._last_activity = time.monotonic()
        except Exception:
            pass

    def exists(self) -> bool:
        """检查面板窗口是否仍然存在且未被销毁。"""
        try:
            return bool(self._win.winfo_exists()) and not self._destroyed
        except Exception:
            return False


# ---------------------------------------------------------------------------
# 主应用程序
# ---------------------------------------------------------------------------


class App:
    """应用程序主控类，协调所有组件（内存监控、托盘图标、悬浮窗口、任务面板）。"""

    def __init__(self):
        # 隐藏的根窗口（Tk 主循环载体）
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.title("SysTray 任务定时器")

        # 任务数据存储
        self._tasks = load_tasks()

        # 任务面板引用（None 表示当前未打开）
        self._panel_10min: TaskPanel | None = None
        self._panel_hourly: TaskPanel | None = None

        # 10分钟定时器状态
        self._10min_deadline = time.monotonic() + TEN_MIN_SECONDS

        # 内存监控
        self._mem_percent = 0.0
        self._mem_monitor = MemoryMonitor(on_update=self._on_mem_update)

        # 悬浮窗口
        self._floating = FloatingWidget(self._root, self)

        # 系统托盘图标
        self._tray_icon = None
        if HAS_PYSTRAY:
            self._setup_tray()

        # 启动内存监控后台线程
        self._mem_monitor.start()

        # 通过 tkinter.after 调度定时检查（在主线程中运行以确保线程安全）
        self._schedule_10min_check()
        self._schedule_hourly_check()

        # 记录上一次整点触发的小时数，防止同一小时内重复触发
        self._last_hourly_fire_hour = -1

    # -- 系统托盘图标 --

    def _setup_tray(self) -> None:
        """初始化系统托盘图标，包含右键菜单。"""
        img = _make_tray_image(0)
        menu = pystray.Menu(
            pystray.MenuItem("显示10分钟任务", lambda: self._root.after(0, self.show_10min_panel)),
            pystray.MenuItem("显示小时任务", lambda: self._root.after(0, self.show_hourly_panel)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: self._root.after(0, self.quit)),
        )
        self._tray_icon = pystray.Icon("TaskTimer", img, "内存: 0%", menu)
        # 在单独的守护线程中运行托盘图标
        t = threading.Thread(target=self._tray_icon.run, daemon=True, name="TrayIcon")
        t.start()

    def _update_tray(self, percent: float) -> None:
        """更新系统托盘图标的图片和悬停提示文字。"""
        if self._tray_icon and HAS_PYSTRAY:
            try:
                self._tray_icon.icon = _make_tray_image(percent)
                self._tray_icon.title = f"内存: {percent:.1f}%"
            except Exception as e:
                print(f"托盘图标更新异常: {e}")

    # -- 内存回调 --

    def _on_mem_update(self, percent: float) -> None:
        """内存监控线程的回调函数（在后台线程中调用）。
        通过 root.after(0, ...) 将 UI 更新调度到主线程。"""
        self._mem_percent = percent
        try:
            self._root.after(0, lambda: self._apply_mem_update(percent))
        except Exception:
            pass

    def _apply_mem_update(self, percent: float) -> None:
        """在主线程中执行 UI 更新：刷新悬浮窗口和托盘图标。"""
        if self._floating.exists():
            self._floating.update_memory(percent)
        self._update_tray(percent)

    # -- 10分钟定时器 --

    def restart_10min_timer(self) -> None:
        """重置10分钟倒计时（在任务文本被修改时调用）。"""
        self._10min_deadline = time.monotonic() + TEN_MIN_SECONDS

    def get_10min_remaining(self) -> int:
        """返回10分钟定时器的剩余秒数。"""
        remaining = self._10min_deadline - time.monotonic()
        return max(0, int(remaining))

    def _schedule_10min_check(self) -> None:
        """启动10分钟定时器的周期检查。"""
        self._root.after(1000, self._check_10min_timer)

    def _check_10min_timer(self) -> None:
        """每秒检查一次10分钟定时器是否到期。"""
        if time.monotonic() >= self._10min_deadline:
            # 重置定时器后触发弹窗，避免重复触发
            self._10min_deadline = time.monotonic() + TEN_MIN_SECONDS
            self._on_10min_fire()
        self._root.after(1000, self._check_10min_timer)

    def _on_10min_fire(self) -> None:
        """10分钟定时器到期：弹出10分钟任务面板并闪烁提醒。"""
        self.show_10min_panel()
        if self._panel_10min and self._panel_10min.exists():
            self._panel_10min.flash()

    # -- 整点小时定时器 --

    def _schedule_hourly_check(self) -> None:
        """启动整点小时定时器的周期检查。"""
        self._root.after(1000, self._check_hourly_timer)

    def _check_hourly_timer(self) -> None:
        """每秒检查一次是否到达整点。
        使用小时数去重，避免在同一秒内重复触发或因检测延迟而错过触发。"""
        now = datetime.datetime.now()
        # 当前分钟为0且秒数在0-2之间视为整点（容忍3秒窗口，覆盖0/1/2秒）
        if now.minute == 0 and now.second <= 2:
            current_hour = now.hour
            if current_hour != self._last_hourly_fire_hour:
                self._last_hourly_fire_hour = current_hour
                self._on_hourly_fire()
        self._root.after(1000, self._check_hourly_timer)

    def _on_hourly_fire(self) -> None:
        """整点触发：弹出小时任务面板并闪烁提醒。"""
        self.show_hourly_panel()
        if self._panel_hourly and self._panel_hourly.exists():
            self._panel_hourly.flash()

    # -- 面板管理 --

    def show_10min_panel(self) -> None:
        """显示10分钟任务面板（若已打开则提升到前台）。"""
        if self._panel_10min and self._panel_10min.exists():
            self._panel_10min.lift()
        else:
            self._panel_10min = TaskPanel(self._root, self, "10min")

    def show_hourly_panel(self) -> None:
        """显示小时任务面板（若已打开则提升到前台）。"""
        if self._panel_hourly and self._panel_hourly.exists():
            self._panel_hourly.lift()
        else:
            self._panel_hourly = TaskPanel(self._root, self, "hourly")

    def on_panel_closed(self, mode: str) -> None:
        """面板关闭时的回调，清除对应面板的引用。"""
        if mode == "10min":
            self._panel_10min = None
        else:
            self._panel_hourly = None

    # -- 任务数据访问 --

    def get_tasks(self, mode: str) -> list[str]:
        """获取指定模式（'10min' 或 'hourly'）的任务列表副本。"""
        return list(self._tasks[mode])

    def set_tasks(self, mode: str, tasks: list[str]) -> None:
        """更新指定模式的任务列表并保存到文件。"""
        self._tasks[mode] = list(tasks)
        save_tasks(self._tasks)

    # -- 悬浮窗口位置 --

    def get_floating_widget_pos(self) -> tuple[int, int]:
        """获取悬浮窗口的当前坐标，用于定位任务面板。"""
        return self._floating.get_position()

    # -- 退出 --

    def quit(self) -> None:
        """退出应用程序：保存任务、停止监控、关闭托盘图标和主循环。"""
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
        """启动应用程序主循环。"""
        self._root.mainloop()


# ---------------------------------------------------------------------------
# 程序入口
# ---------------------------------------------------------------------------


def main() -> None:
    """创建并启动应用程序。"""
    app = App()
    app.run()


if __name__ == "__main__":
    main()
