#!/usr/bin/env python3
"""
Unit tests for systray_task.py (non-GUI, non-tray logic).
Run with: python3 test_systray_task.py
"""

import datetime
import json
import os
import tempfile
import unittest


# ── Inline the pure-logic functions from systray_task.py ──────────────────
MEM_ORANGE_THRESHOLD = 80
MEM_RED_THRESHOLD = 90
KILL_THRESHOLD = 94
KILL_PROCESS_ORDER = ["chrome", "msedge", "edge", "java", "code"]
NUM_10MIN_TASKS = 5
NUM_HOURLY_TASKS = 20
COLOR_GREEN = "#00cc00"
COLOR_ORANGE = "#ff8800"
COLOR_RED = "#ff2200"


def get_mem_color(percent: float) -> str:
    if percent < MEM_ORANGE_THRESHOLD:
        return COLOR_GREEN
    elif percent < MEM_RED_THRESHOLD:
        return COLOR_ORANGE
    else:
        return COLOR_RED


def now_str() -> str:
    return datetime.datetime.now().strftime("%Y:%m:%d %H:%M.%S")


def next_whole_hour() -> datetime.datetime:
    now = datetime.datetime.now()
    return (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)


def log_completed_task_to(path: str, task_text: str) -> None:
    entry = f"{now_str()} Finish Task: {task_text}\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)


def load_tasks(path: str) -> dict:
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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


# ── Tests ──────────────────────────────────────────────────────────────────


class TestMemColor(unittest.TestCase):
    def test_below_orange(self):
        self.assertEqual(get_mem_color(0), COLOR_GREEN)
        self.assertEqual(get_mem_color(50), COLOR_GREEN)
        self.assertEqual(get_mem_color(79.9), COLOR_GREEN)

    def test_orange_range(self):
        self.assertEqual(get_mem_color(80), COLOR_ORANGE)
        self.assertEqual(get_mem_color(85), COLOR_ORANGE)
        self.assertEqual(get_mem_color(89.9), COLOR_ORANGE)

    def test_red_range(self):
        self.assertEqual(get_mem_color(90), COLOR_RED)
        self.assertEqual(get_mem_color(94), COLOR_RED)
        self.assertEqual(get_mem_color(100), COLOR_RED)


class TestNowStr(unittest.TestCase):
    def test_format(self):
        s = now_str()
        # Expected: YYYY:MM:DD HH:MM.SS  (19 chars)
        self.assertEqual(len(s), 19, f"Unexpected length for '{s}'")
        # Spot-check separators
        self.assertEqual(s[4], ":")
        self.assertEqual(s[7], ":")
        self.assertEqual(s[13], ":")
        self.assertEqual(s[16], ".")


class TestNextWholeHour(unittest.TestCase):
    def test_on_the_hour(self):
        nh = next_whole_hour()
        self.assertEqual(nh.minute, 0)
        self.assertEqual(nh.second, 0)
        self.assertEqual(nh.microsecond, 0)

    def test_in_the_future(self):
        now = datetime.datetime.now()
        nh = next_whole_hour()
        self.assertGreater(nh, now)

    def test_less_than_one_hour(self):
        now = datetime.datetime.now()
        nh = next_whole_hour()
        delta = (nh - now).total_seconds()
        self.assertLessEqual(delta, 3600)


class TestTaskStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)  # Remove so load_tasks returns default

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_default_structure(self):
        tasks = load_tasks(self.tmp.name)
        self.assertEqual(len(tasks["10min"]), NUM_10MIN_TASKS)
        self.assertEqual(len(tasks["hourly"]), NUM_HOURLY_TASKS)
        self.assertTrue(all(t == "" for t in tasks["10min"]))

    def test_save_and_load(self):
        tasks = load_tasks(self.tmp.name)
        tasks["10min"][0] = "Task A"
        tasks["hourly"][5] = "Task B"
        save_tasks(self.tmp.name, tasks)

        loaded = load_tasks(self.tmp.name)
        self.assertEqual(loaded["10min"][0], "Task A")
        self.assertEqual(loaded["hourly"][5], "Task B")

    def test_load_truncates_to_max(self):
        # Save a list that is longer than NUM_10MIN_TASKS
        data = {"10min": ["x"] * 10, "hourly": ["y"] * 25}
        save_tasks(self.tmp.name, data)
        loaded = load_tasks(self.tmp.name)
        self.assertEqual(len(loaded["10min"]), NUM_10MIN_TASKS)
        self.assertEqual(len(loaded["hourly"]), NUM_HOURLY_TASKS)

    def test_load_pads_short_lists(self):
        data = {"10min": ["a"], "hourly": ["b"]}
        save_tasks(self.tmp.name, data)
        loaded = load_tasks(self.tmp.name)
        self.assertEqual(len(loaded["10min"]), NUM_10MIN_TASKS)
        self.assertEqual(loaded["10min"][0], "a")
        self.assertEqual(loaded["10min"][1], "")


class TestLogCompletedTask(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w")
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_log_entry_format(self):
        log_completed_task_to(self.tmp.name, "Write tests")
        with open(self.tmp.name, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Finish Task: Write tests", content)
        # Should have a timestamp at start
        line = content.strip().split("\n")[0]
        # Format: YYYY:MM:DD HH:MM.SS Finish Task: ...
        parts = line.split(" ")
        self.assertGreaterEqual(len(parts), 4)
        # Date part
        self.assertEqual(len(parts[0]), 10)
        self.assertEqual(parts[0][4], ":")

    def test_log_appends(self):
        log_completed_task_to(self.tmp.name, "Task 1")
        log_completed_task_to(self.tmp.name, "Task 2")
        with open(self.tmp.name, encoding="utf-8") as f:
            lines = [l for l in f.readlines() if l.strip()]
        self.assertEqual(len(lines), 2)
        self.assertIn("Task 1", lines[0])
        self.assertIn("Task 2", lines[1])


class TestKillOrder(unittest.TestCase):
    def _find_first_to_kill(self, running_names):
        """Simulate which process would be killed first."""
        running_set = set(n.lower() for n in running_names)
        for name in KILL_PROCESS_ORDER:
            if name in running_set:
                return name
        return None

    def test_chrome_before_edge(self):
        result = self._find_first_to_kill(["edge", "chrome", "java"])
        self.assertEqual(result, "chrome")

    def test_edge_before_java(self):
        result = self._find_first_to_kill(["java", "edge"])
        self.assertEqual(result, "edge")

    def test_java_before_code(self):
        result = self._find_first_to_kill(["code", "java"])
        self.assertEqual(result, "java")

    def test_no_matching_process(self):
        result = self._find_first_to_kill(["python", "bash"])
        self.assertIsNone(result)

    def test_only_code(self):
        result = self._find_first_to_kill(["code"])
        self.assertEqual(result, "code")


class TestTaskCompletion(unittest.TestCase):
    """Simulate the task-shift logic applied when a task is completed."""

    def _complete_task(self, tasks: list[str], index: int) -> list[str]:
        tasks = list(tasks)
        tasks.pop(index)
        tasks.append("")
        return tasks

    def test_shift_up_after_completion(self):
        tasks = ["A", "B", "C", "D", "E"]
        result = self._complete_task(tasks, 0)
        self.assertEqual(result, ["B", "C", "D", "E", ""])

    def test_complete_middle(self):
        tasks = ["A", "B", "C", "D", "E"]
        result = self._complete_task(tasks, 2)
        self.assertEqual(result, ["A", "B", "D", "E", ""])

    def test_complete_last(self):
        tasks = ["A", "B", "C", "D", "E"]
        result = self._complete_task(tasks, 4)
        self.assertEqual(result, ["A", "B", "C", "D", ""])

    def test_length_unchanged(self):
        tasks = ["A", "B", "C", "D", "E"]
        result = self._complete_task(tasks, 1)
        self.assertEqual(len(result), len(tasks))


if __name__ == "__main__":
    unittest.main(verbosity=2)
