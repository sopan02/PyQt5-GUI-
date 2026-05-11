import os
import sys
import time
import threading
from queue import Empty, Queue
from datetime import datetime
import pandas as pd


def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)  # EXE location
    return os.path.abspath(".")


class ExcelLogger:
    def __init__(self):
        base_path = get_base_path()
        data_path = os.path.join(base_path, "data")

        os.makedirs(data_path, exist_ok=True)

        date = datetime.now().strftime("%Y-%m-%d")
        self.file = os.path.join(data_path, f"leakage_log_{date}.xlsx")
        self.rows = []
        self.queue = Queue()
        self.closed = False
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()

    def save(self, text):
        now = datetime.now()
        self.queue.put([
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            text
        ])

    def close(self):
        self.closed = True
        self.worker.join(timeout=3.0)
        self._flush_pending()

    def _worker_loop(self):
        last_flush = time.monotonic()

        while not self.closed:
            try:
                row = self.queue.get(timeout=0.25)
                self.rows.append(row)
            except Empty:
                pass

            elapsed = time.monotonic() - last_flush
            if self.rows and (elapsed >= 1.0 or self.queue.qsize() >= 20):
                self._write_file()
                last_flush = time.monotonic()

        self._flush_pending()

    def _flush_pending(self):
        while True:
            try:
                self.rows.append(self.queue.get_nowait())
            except Empty:
                break

        if self.rows:
            self._write_file()

    def _write_file(self):
        try:
            df = pd.DataFrame(self.rows, columns=["Date", "Time", "Serial Data"])
            df.to_excel(self.file, index=False)
        except Exception as e:
            print("Excel write error:", e)
