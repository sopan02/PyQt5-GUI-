import time
import threading
from queue import Empty, Queue
import serial
from serial.tools import list_ports
from PyQt5.QtCore import QThread, pyqtSignal


class SerialManager(QThread):
    data_received = pyqtSignal(str)
    connection_changed = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__()
        self.running = False
        self.ser = None
        self.port = None
        self._lock = threading.Lock()
        self._tx_queue = Queue()

    def available_ports(self):
        return list(list_ports.comports())

    def find_arduino_port(self):
        ports = self.available_ports()
        keywords = ("arduino", "ch340", "wch", "usb serial", "usb-sERIAL", "mega")

        for p in ports:
            desc = f"{p.description} {p.manufacturer} {p.hwid}".lower()
            if any(k.lower() in desc for k in keywords):
                return p.device

        return ports[0].device if ports else None

    def start_serial(self, port):
        if self.isRunning():
            return

        self.port = port
        self._clear_tx_queue()
        self.running = True
        self.start()

    def run(self):
        try:
            self.ser = serial.Serial(self.port, 9600, timeout=0.2, write_timeout=0.5)
            time.sleep(2.0)
            self.connection_changed.emit(True, self.port)

            self.send("CMD:STATUS?")

            while self.running:
                self._write_queued_commands()

                if self.ser and self.ser.in_waiting:
                    line = self.ser.readline().decode(errors="ignore").strip()
                    if line:
                        self.data_received.emit(line)
                else:
                    time.sleep(0.02)

        except Exception as e:
            self.data_received.emit(f"GUI_SERIAL_ERROR: {e}")

        finally:
            try:
                if self.ser:
                    self.ser.close()
            except Exception:
                pass

            self.ser = None
            self.running = False
            self._clear_tx_queue()
            self.connection_changed.emit(False, self.port or "")

    def send(self, text):
        if not text:
            return False

        self._tx_queue.put(text.strip())
        return True

    def _write_queued_commands(self):
        while self.running:
            try:
                text = self._tx_queue.get_nowait()
            except Empty:
                return

            try:
                with self._lock:
                    if self.ser and self.ser.is_open:
                        self.ser.write((text + "\n").encode("utf-8"))
                    else:
                        self.data_received.emit(f"GUI_SERIAL_ERROR: command dropped while disconnected: {text}")
            except Exception as e:
                self.data_received.emit(f"GUI_SERIAL_ERROR: failed to send {text}: {e}")

    def _clear_tx_queue(self):
        while True:
            try:
                self._tx_queue.get_nowait()
            except Empty:
                return

    def send_immediate(self, text):
        with self._lock:
            if self.ser and self.ser.is_open:
                self.ser.write((text.strip() + "\n").encode("utf-8"))

    def stop_serial(self):
        self.running = False
        self.wait(1500)
