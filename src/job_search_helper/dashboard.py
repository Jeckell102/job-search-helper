"""Terminal dashboard for long scraper runs."""
from __future__ import annotations

import os
import sys
import time
from collections import deque
from threading import Lock


WORKER_COLORS = ("33", "36", "35", "34", "31", "96", "95", "94", "93", "91")
WRITER_COLOR = "32"


def _stamp():
    return time.strftime("%H:%M:%S")


def _duration(seconds):
    seconds = max(0, int(seconds or 0))
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{remainder:02d}s"
    if minutes:
        return f"{minutes}m{remainder:02d}s"
    return f"{remainder}s"


def _clip(value, width):
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= width:
        return text
    if width <= 3:
        return "." * width
    return text[:width - 3].rstrip() + "..."


class TerminalDashboard:
    def __init__(self, workers, stream=None, max_rows=14):
        self.workers = workers
        self.stream = stream or sys.stdout
        self.max_rows = max_rows
        self.lock = Lock()
        self.interactive = bool(
            getattr(self.stream, "isatty", lambda: False)()
            and os.environ.get("TERM", "") not in {"", "dumb"}
        )
        self.worker_state = {
            slot: {"task": "Idle", "company": "", "detail": ""}
            for slot in range(1, workers + 1)
        }
        self.writer_state = {"task": "Idle", "company": "", "progress": "", "duration": "0s"}
        self.worker_events = deque(maxlen=max_rows)
        self.job_events = deque(maxlen=max_rows)
        self.inventory_count = 0
        self.new_job_count = 0
        self.started_at = time.monotonic()

    def start(self):
        self.render()

    def worker_fetching(self, slot, company):
        with self.lock:
            self.worker_state[slot] = {"task": "Fetching", "company": company, "detail": ""}
            self._render_locked()

    def worker_handoff(self, slot, company, job_count):
        with self.lock:
            self.worker_state[slot] = {"task": "Ready", "company": company, "detail": f"{job_count} jobs"}
            self.worker_events.appendleft(f"Worker {slot} - {job_count} jobs - {company} - {_stamp()}")
            self._render_locked()

    def worker_failed(self, slot, company):
        with self.lock:
            self.worker_state[slot] = {"task": "Failed", "company": company, "detail": ""}
            self.worker_events.appendleft(f"Worker {slot} - failed - {company} - {_stamp()}")
            self._render_locked()

    def writer_progress(self, company, done, total, elapsed, processed=0):
        with self.lock:
            self.inventory_count += processed
            self.writer_state = {
                "task": "Saving",
                "company": company,
                "progress": f"{done}/{total}",
                "duration": _duration(elapsed),
            }
            self._render_locked()

    def writer_message(self, task, company="", progress="", elapsed=None):
        with self.lock:
            self.writer_state = {
                "task": task,
                "company": company,
                "progress": progress,
                "duration": _duration(time.monotonic() - self.started_at if elapsed is None else elapsed),
            }
            self._render_locked()

    def job_written(self, title, company):
        with self.lock:
            self.new_job_count += 1
            self.job_events.appendleft(f"{_clip(title, 42)} at {_clip(company, 28)} - {_stamp()}")
            self._render_locked()

    def render(self):
        with self.lock:
            self._render_locked()

    def _color(self, text, color):
        if not self.interactive:
            return text
        return f"\033[{color}m{text}\033[0m"

    def _render_locked(self):
        if not self.interactive:
            self._render_event_log()
            return
        rows = ["\033[2J\033[HJob Search Scraper Dashboard"]
        rows.append(
            f"Run time: {_duration(time.monotonic() - self.started_at)} | "
            f"Inventory processed: {self.inventory_count} | New jobs written: {self.new_job_count}"
        )
        rows.append("")
        for slot in range(1, self.workers + 1):
            state = self.worker_state[slot]
            text = f"Worker {slot} - {state['task']}"
            if state["company"]:
                text += f" - {state['company']}"
            if state["detail"]:
                text += f" - {state['detail']}"
            rows.append(self._color(_clip(text, 120), WORKER_COLORS[(slot - 1) % len(WORKER_COLORS)]))
        writer = f"Writer - {self.writer_state['task']}"
        if self.writer_state["company"]:
            writer += f" - {self.writer_state['company']}"
        if self.writer_state["progress"]:
            writer += f" - {self.writer_state['progress']}"
        writer += f" - {self.writer_state['duration']}"
        rows.append(self._color(_clip(writer, 120), WRITER_COLOR))
        rows.append("")
        left_width = 58
        rows.append(f"{'Workers':<{left_width}} Jobs")
        rows.append(f"{'-' * 7:<{left_width}} {'-' * 4}")
        for left, right in self._paired_events():
            rows.append(f"{_clip(left, left_width - 1):<{left_width}} {_clip(right, 64)}")
        self.stream.write("\n".join(rows) + "\n")
        self.stream.flush()

    def _render_event_log(self):
        worker_bits = []
        for slot in range(1, self.workers + 1):
            state = self.worker_state[slot]
            bit = f"Worker {slot} - {state['task']}"
            if state["company"]:
                bit += f" - {state['company']}"
            if state["detail"]:
                bit += f" - {state['detail']}"
            worker_bits.append(bit)
        writer = f"Writer - {self.writer_state['task']}"
        if self.writer_state["company"]:
            writer += f" - {self.writer_state['company']}"
        if self.writer_state["progress"]:
            writer += f" - {self.writer_state['progress']}"
        writer += f" - {self.writer_state['duration']}"
        self.stream.write(
            "Dashboard | " + " | ".join(worker_bits)
            + f" | {writer} | Inventory processed: {self.inventory_count} | New jobs written: {self.new_job_count}\n"
        )
        if self.worker_events:
            self.stream.write(f"Workers | {self.worker_events[0]}\n")
        if self.job_events:
            self.stream.write(f"Jobs | {self.job_events[0]}\n")
        self.stream.flush()

    def _paired_events(self):
        count = max(len(self.worker_events), len(self.job_events), 1)
        for index in range(min(count, self.max_rows)):
            left = self.worker_events[index] if index < len(self.worker_events) else ""
            right = self.job_events[index] if index < len(self.job_events) else ""
            yield left, right
