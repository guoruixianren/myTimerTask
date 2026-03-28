#!/usr/bin/env python3
"""
systray_task.py 的单元测试（仅测试非GUI纯逻辑部分）。
运行方式: python3 test_systray_task.py
"""

import datetime
import json
import os
import tempfile
import unittest


# ── 从 systray_task.py 中复制的纯逻辑函数和常量（用于独立测试） ──────────
MEM_ORANGE_THRESHOLD = 80       # 橙色阈值
MEM_RED_THRESHOLD = 90          # 红色阈值
KILL_THRESHOLD = 94             # 开始杀进程的阈值
KILL_PROCESS_ORDER = ["chrome", "msedge", "edge", "java", "code"]  # 杀进程优先级
NUM_10MIN_TASKS = 5             # 10分钟任务条数
NUM_HOURLY_TASKS = 20           # 小时任务条数
COLOR_GREEN = "#00cc00"         # 绿色（内存正常）
COLOR_ORANGE = "#ff8800"        # 橙色（内存警告）
COLOR_RED = "#ff2200"           # 红色（内存危险）


def get_mem_color(percent: float) -> str:
    """根据内存百分比返回对应颜色。"""
    if percent < MEM_ORANGE_THRESHOLD:
        return COLOR_GREEN
    elif percent < MEM_RED_THRESHOLD:
        return COLOR_ORANGE
    else:
        return COLOR_RED


def now_str() -> str:
    """返回当前时间格式化字符串。"""
    return datetime.datetime.now().strftime("%Y:%m:%d %H:%M.%S")


def next_whole_hour() -> datetime.datetime:
    """计算下一个整点小时。"""
    now = datetime.datetime.now()
    return (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)


def log_completed_task_to(path: str, task_text: str) -> None:
    """将完成的任务追加到指定日志文件。"""
    entry = f"{now_str()} Finish Task: {task_text}\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)


def load_tasks(path: str) -> dict:
    """从指定路径加载任务列表，不足补空，超出截断。"""
    default = {
        "10min": [""] * NUM_10MIN_TASKS,
        "hourly": [""] * NUM_HOURLY_TASKS,
    }
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            t10 = data.get("10min", [])
            th = data.get("hourly", [])
            while len(t10) < NUM_10MIN_TASKS:
                t10.append("")
            while len(th) < NUM_HOURLY_TASKS:
                th.append("")
            return {"10min": t10[:NUM_10MIN_TASKS], "hourly": th[:NUM_HOURLY_TASKS]}
    except Exception:
        pass
    return default


def save_tasks(path: str, tasks: dict) -> None:
    """将任务列表保存到指定路径的 JSON 文件。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


# ── 测试用例 ──────────────────────────────────────────────────────────────


class TestMemColor(unittest.TestCase):
    """测试内存百分比对应颜色的分级逻辑。"""

    def test_below_orange(self):
        """低于80%应返回绿色。"""
        self.assertEqual(get_mem_color(0), COLOR_GREEN)
        self.assertEqual(get_mem_color(50), COLOR_GREEN)
        self.assertEqual(get_mem_color(79.9), COLOR_GREEN)

    def test_orange_range(self):
        """80%-90%之间应返回橙色。"""
        self.assertEqual(get_mem_color(80), COLOR_ORANGE)
        self.assertEqual(get_mem_color(85), COLOR_ORANGE)
        self.assertEqual(get_mem_color(89.9), COLOR_ORANGE)

    def test_red_range(self):
        """90%及以上应返回红色。"""
        self.assertEqual(get_mem_color(90), COLOR_RED)
        self.assertEqual(get_mem_color(94), COLOR_RED)
        self.assertEqual(get_mem_color(100), COLOR_RED)


class TestNowStr(unittest.TestCase):
    """测试时间格式化字符串。"""

    def test_format(self):
        """验证格式为 YYYY:MM:DD HH:MM.SS（19个字符）。"""
        s = now_str()
        self.assertEqual(len(s), 19, f"字符串长度不符预期: '{s}'")
        # 检查分隔符位置
        self.assertEqual(s[4], ":")
        self.assertEqual(s[7], ":")
        self.assertEqual(s[13], ":")
        self.assertEqual(s[16], ".")


class TestNextWholeHour(unittest.TestCase):
    """测试下一个整点小时的计算。"""

    def test_on_the_hour(self):
        """返回的时间应在整点（分秒为0）。"""
        nh = next_whole_hour()
        self.assertEqual(nh.minute, 0)
        self.assertEqual(nh.second, 0)
        self.assertEqual(nh.microsecond, 0)

    def test_in_the_future(self):
        """返回的时间应在当前时间之后。"""
        now = datetime.datetime.now()
        nh = next_whole_hour()
        self.assertGreater(nh, now)

    def test_less_than_one_hour(self):
        """距下一个整点应不超过1小时。"""
        now = datetime.datetime.now()
        nh = next_whole_hour()
        delta = (nh - now).total_seconds()
        self.assertLessEqual(delta, 3600)


class TestTaskStorage(unittest.TestCase):
    """测试任务数据的加载和保存。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)  # 删除文件以测试默认返回值

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_default_structure(self):
        """文件不存在时应返回默认结构（全空字符串列表）。"""
        tasks = load_tasks(self.tmp.name)
        self.assertEqual(len(tasks["10min"]), NUM_10MIN_TASKS)
        self.assertEqual(len(tasks["hourly"]), NUM_HOURLY_TASKS)
        self.assertTrue(all(t == "" for t in tasks["10min"]))

    def test_save_and_load(self):
        """保存后加载应恢复相同数据。"""
        tasks = load_tasks(self.tmp.name)
        tasks["10min"][0] = "Task A"
        tasks["hourly"][5] = "Task B"
        save_tasks(self.tmp.name, tasks)

        loaded = load_tasks(self.tmp.name)
        self.assertEqual(loaded["10min"][0], "Task A")
        self.assertEqual(loaded["hourly"][5], "Task B")

    def test_load_truncates_to_max(self):
        """超出最大长度的列表应被截断。"""
        data = {"10min": ["x"] * 10, "hourly": ["y"] * 25}
        save_tasks(self.tmp.name, data)
        loaded = load_tasks(self.tmp.name)
        self.assertEqual(len(loaded["10min"]), NUM_10MIN_TASKS)
        self.assertEqual(len(loaded["hourly"]), NUM_HOURLY_TASKS)

    def test_load_pads_short_lists(self):
        """不足最大长度的列表应被补空。"""
        data = {"10min": ["a"], "hourly": ["b"]}
        save_tasks(self.tmp.name, data)
        loaded = load_tasks(self.tmp.name)
        self.assertEqual(len(loaded["10min"]), NUM_10MIN_TASKS)
        self.assertEqual(loaded["10min"][0], "a")
        self.assertEqual(loaded["10min"][1], "")


class TestLogCompletedTask(unittest.TestCase):
    """测试已完成任务的日志记录。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_log_entry_format(self):
        """日志格式应为: YYYY:MM:DD HH:MM.SS Finish Task: 任务内容"""
        log_completed_task_to(self.tmp.name, "Write tests")
        with open(self.tmp.name, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Finish Task: Write tests", content)
        # 检查时间戳格式
        line = content.strip().split("\n")[0]
        parts = line.split(" ")
        self.assertGreaterEqual(len(parts), 4)
        # 日期部分长度为10（YYYY:MM:DD）
        self.assertEqual(len(parts[0]), 10)
        self.assertEqual(parts[0][4], ":")

    def test_log_appends(self):
        """多次写入应追加而非覆盖。"""
        log_completed_task_to(self.tmp.name, "Task 1")
        log_completed_task_to(self.tmp.name, "Task 2")
        with open(self.tmp.name, encoding="utf-8") as f:
            lines = [l for l in f.readlines() if l.strip()]
        self.assertEqual(len(lines), 2)
        self.assertIn("Task 1", lines[0])
        self.assertIn("Task 2", lines[1])


class TestKillOrder(unittest.TestCase):
    """测试杀进程的优先级顺序。"""

    def _find_first_to_kill(self, running_names):
        """模拟查找应首先被杀的进程。"""
        running_set = set(n.lower() for n in running_names)
        for name in KILL_PROCESS_ORDER:
            if name in running_set:
                return name
        return None

    def test_chrome_before_edge(self):
        """Chrome 的优先级应高于 Edge。"""
        result = self._find_first_to_kill(["edge", "chrome", "java"])
        self.assertEqual(result, "chrome")

    def test_edge_before_java(self):
        """Edge 的优先级应高于 Java。"""
        result = self._find_first_to_kill(["java", "edge"])
        self.assertEqual(result, "edge")

    def test_java_before_code(self):
        """Java 的优先级应高于 VSCode。"""
        result = self._find_first_to_kill(["code", "java"])
        self.assertEqual(result, "java")

    def test_no_matching_process(self):
        """无匹配进程时应返回 None。"""
        result = self._find_first_to_kill(["python", "bash"])
        self.assertIsNone(result)

    def test_only_code(self):
        """仅有 VSCode 时应返回 code。"""
        result = self._find_first_to_kill(["code"])
        self.assertEqual(result, "code")


class TestTaskCompletion(unittest.TestCase):
    """测试任务完成后的列表移位逻辑。"""

    def _complete_task(self, tasks: list[str], index: int) -> list[str]:
        """模拟完成任务：删除指定行，其余上移，末行补空。"""
        tasks = list(tasks)
        tasks.pop(index)
        tasks.append("")
        return tasks

    def test_shift_up_after_completion(self):
        """完成第一条任务后，其余应上移。"""
        tasks = ["A", "B", "C", "D", "E"]
        result = self._complete_task(tasks, 0)
        self.assertEqual(result, ["B", "C", "D", "E", ""])

    def test_complete_middle(self):
        """完成中间任务后，后续应上移。"""
        tasks = ["A", "B", "C", "D", "E"]
        result = self._complete_task(tasks, 2)
        self.assertEqual(result, ["A", "B", "D", "E", ""])

    def test_complete_last(self):
        """完成最后一条任务后，该位置变为空。"""
        tasks = ["A", "B", "C", "D", "E"]
        result = self._complete_task(tasks, 4)
        self.assertEqual(result, ["A", "B", "C", "D", ""])

    def test_length_unchanged(self):
        """完成任务后列表长度应保持不变。"""
        tasks = ["A", "B", "C", "D", "E"]
        result = self._complete_task(tasks, 1)
        self.assertEqual(len(result), len(tasks))


if __name__ == "__main__":
    unittest.main(verbosity=2)
