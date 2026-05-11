import os
import sys
import winsound
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import *

from core.serial_manager import SerialManager
from core.logger import ExcelLogger


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LEAKAGE TESTER GUI")

        self.serial = SerialManager()
        self.logger = ExcelLogger()

        self.running = False
        self.run_blink = False
        self.error_active = False
        self.error_blink = False
        self.fixture_ready = False
        self.operator_pixmaps = {}
        self.current_operator_image = None
        self.engineering_seen_messages = set()

        self.build_ui()

        self.run_timer = QTimer(self)
        self.run_timer.timeout.connect(self.blink_run_lamp)

        self.error_timer = QTimer(self)
        self.error_timer.timeout.connect(self.blink_error_lamp)

        self.start_hold_active = False
        self.start_hold_timer = QTimer(self)
        self.start_hold_timer.setInterval(200)
        self.start_hold_timer.timeout.connect(self.send_start_hold_tick)

        self.stop_hold_active = False
        self.stop_long_mode = False
        self.stop_hold_delay_timer = QTimer(self)
        self.stop_hold_delay_timer.setSingleShot(True)
        self.stop_hold_delay_timer.timeout.connect(self.begin_stop_hold)
        self.stop_hold_timer = QTimer(self)
        self.stop_hold_timer.setInterval(200)
        self.stop_hold_timer.timeout.connect(self.send_stop_hold_tick)

        self.port_timer = QTimer(self)
        self.port_timer.timeout.connect(self.auto_detect_port)
        self.port_timer.start(2000)

        self.handshake_timer = QTimer(self)
        self.handshake_timer.setSingleShot(True)
        self.handshake_timer.timeout.connect(self.fixture_handshake_timeout)

        self.init_state()

        self.serial.data_received.connect(self.handle_serial)
        self.serial.connection_changed.connect(self.on_connection_changed)

        self.auto_detect_port()

    def build_ui(self):
        root = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.operator_ui(), "OPERATOR")
        self.tabs.addTab(self.engineering_ui(), "ENGINEERING")

        root.addWidget(self.tabs)

    def operator_ui(self):
        tab = QWidget()
        main = QVBoxLayout(tab)

        top = QHBoxLayout()

        self.portBox = QComboBox()

        self.connectBtn = QPushButton("CONNECT")
        self.connectBtn.setFixedSize(140, 36)
        self.connectBtn.clicked.connect(self.toggle_connection)

        self.logo = QLabel()
        self.logo.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        logo_path = resource_path(os.path.join("images", "logo.png"))
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            self.logo.setPixmap(pixmap.scaledToHeight(55, Qt.SmoothTransformation))
        else:
            self.logo.setText("LOGO")

        top.addWidget(QLabel("COM PORT"))
        top.addWidget(self.portBox)
        top.addWidget(self.connectBtn)
        top.addStretch()
        top.addWidget(self.logo)
        main.addLayout(top)

        content = QHBoxLayout()
        left = QVBoxLayout()
        right = QVBoxLayout()

        self.instructions = QTextEdit()
        self.instructions.setReadOnly(True)
        self.instructions.setFixedHeight(230)
        self.instructions.setStyleSheet("""
            QTextEdit {
                background-color: #071d11;
                color: #00ff66;
                font: bold 30px Consolas;
                padding: 14px;
                border: 2px solid #111;
            }
        """)
        left.addWidget(self.instructions)

        middle = QHBoxLayout()

        status_layout = QVBoxLayout()
        self.fixture = self.make_small_status("TESTER CONNECTED")
        self.dut_connected = self.make_small_status("DUT FIXTURE CONNECTED")
        self.dut_inserted = self.make_small_status("DUT INSERTED")
        self.door = self.make_small_status("DOOR CLOSED")

        self.dut_type_label = QLabel("DUT TYPE: --")
        self.dut_type_label.setAlignment(Qt.AlignCenter)
        self.dut_type_label.setFixedHeight(46)
        self.dut_type_label.setStyleSheet("background:#e9ecef; border:1px solid #222; font:bold 17px;")

        for item in (self.fixture, self.dut_connected, self.dut_type_label, self.dut_inserted, self.door):
            status_layout.addWidget(item)

        self.run_lamp = self.make_lamp("TEST\nRUNNING")
        self.pass_lamp = self.make_lamp("DUT\nPASSED")
        self.fail_lamp = self.make_lamp("DUT\nFAILED")
        self.error_lamp = self.make_lamp("ERROR")

        # Lamps section is intentionally hidden for now.
        # To show it again, uncomment this block and the middle.addLayout line below.
        # lamp_layout = QHBoxLayout()
        # for lamp in (self.run_lamp, self.pass_lamp, self.fail_lamp, self.error_lamp):
        #     lamp_layout.addWidget(lamp)

        middle.addLayout(status_layout, 2)
        # middle.addLayout(lamp_layout, 4)
        left.addLayout(middle)

        bottom = QHBoxLayout()

        self.start_btn = QPushButton("START")
        self.start_btn.setFixedSize(170, 70)
        self.start_btn.setStyleSheet("background:#2ecc71; color:white; font:bold 22px;")
        self.start_btn.pressed.connect(self.start_pressed)
        self.start_btn.released.connect(self.start_released)

        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setFixedSize(170, 70)
        self.stop_btn.setStyleSheet("background:#e74c3c; color:white; font:bold 22px;")
        self.stop_btn.pressed.connect(self.stop_pressed)
        self.stop_btn.released.connect(self.stop_released)

        bottom.addStretch()
        bottom.addWidget(self.start_btn)
        bottom.addSpacing(40)
        bottom.addWidget(self.stop_btn)
        bottom.addStretch()
        left.addLayout(bottom)

        self.operator_title = QLabel("IMAGES FOR OPERATOR")
        self.operator_title.setAlignment(Qt.AlignCenter)
        self.operator_title.setFixedHeight(34)
        self.operator_title.setStyleSheet("background:white; border:2px solid #111; font:16px;")

        self.operator_image = QLabel()
        self.operator_image.setAlignment(Qt.AlignCenter)
        self.operator_image.setMinimumSize(360, 460)
        self.operator_image.setStyleSheet("background:white; border:3px solid #111;")

        right.addWidget(self.operator_title)
        right.addWidget(self.operator_image, 1)

        content.addLayout(left, 1)
        content.addSpacing(20)
        content.addLayout(right, 1)
        main.addLayout(content, 1)

        self.load_operator_images()

        return tab

    def engineering_ui(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font: 12px Consolas;")

        layout.addWidget(self.log)
        return tab

    def auto_detect_port(self):
        if self.serial.isRunning():
            return

        current = self.portBox.currentText()
        ports = [p.device for p in self.serial.available_ports()]

        self.portBox.blockSignals(True)
        self.portBox.clear()
        self.portBox.addItems(ports if ports else ["NO COM"])
        if current in ports:
            self.portBox.setCurrentText(current)
        self.portBox.blockSignals(False)

        detected = self.serial.find_arduino_port()
        if detected:
            self.portBox.setCurrentText(detected)

    def toggle_connection(self):
        if self.serial.isRunning():
            self.serial.stop_serial()
            return

        port = self.portBox.currentText()
        if not port or "NO COM" in port:
            QMessageBox.warning(self, "COM PORT", "NO COM PORT FOUND.")
            return

        self.fixture_ready = False
        self.connectBtn.setText("CHECKING...")
        self.connectBtn.setStyleSheet("background:#f39c12; color:white; font:bold 13px;")
        self.instructions.setText("OPENING SERIAL PORT\nWAITING FOR FIXTURE...")
        self.serial.start_serial(port)

    def on_connection_changed(self, connected, port):
        if connected:
            self.fixture_ready = False
            self.connectBtn.setText("CHECKING...")
            self.connectBtn.setStyleSheet("background:#f39c12; color:white; font:bold 13px;")
            self.set_status(self.fixture, False)
            self.instructions.setText("SERIAL PORT OPENED\nWAITING FOR FIXTURE\nPLEASE WAIT...")
            self.append_engineering_log(f"SERIAL PORT OPENED: {port}")
            self.handshake_timer.start(5000)
        else:
            self.fixture_ready = False
            self.handshake_timer.stop()
            self.connectBtn.setText("CONNECT")
            self.connectBtn.setStyleSheet("background:#8a8f98; color:white; font:bold 13px;")
            self.reset_all_states()
            self.instructions.setText("NO TESTER CONNECTED\nSELECT ARDUINO COM PORT\nPRESS CONNECT")
            if port:
                self.append_engineering_log(f"CONNECT: {port}")

    def fixture_handshake_timeout(self):
        if self.fixture_ready:
            return

        self.append_engineering_log("FIXTURE HANDSHAKE FAILED: NO GUI:READY RECEIVED.")
        QMessageBox.warning(
            self,
            "FIXTURE NOT DETECTED",
            "COM PORT OPENED, BUT LEAKAGE FIXTURE DID NOT RESPOND.\n\n"
            "PLEASE CONNECT ARDUINO FIXTURE AND SELECT CORRECT COM PORT."
        )
        self.serial.stop_serial()

    def handle_serial(self, text):
        self.append_engineering_log(text)
        self.logger.save(text)

        upper = text.upper()

        if "GUI_SERIAL_ERROR" in upper:
            return

        if "GUI:READY" in upper:
            self.fixture_ready = True
            self.handshake_timer.stop()
            self.connectBtn.setText("CONNECTED")
            self.connectBtn.setStyleSheet("background:#1f9d55; color:white; font:bold 13px;")
            self.set_status(self.fixture, True)
            self.instructions.setText("TESTER CONNECTED\nWAITING FOR DUT...")
            self.update_operator_image("start")
            return

        if not self.fixture_ready:
            return

        if text.startswith("GUI:LCD="):
            payload = text.split("=", 1)[1]
            lines = payload.split("|")
            self.instructions.setText("\n".join(line.upper() for line in lines))

        if text.startswith("GUI:DUT_TYPE="):
            dut = text.split("=", 1)[1].strip()
            self.dut_type_label.setText(f"DUT TYPE: {dut.upper()}")
            self.set_status(self.dut_connected, bool(dut))
            return

        if self.error_active and (
            "PRESS START" in upper
            or "READY TO START" in upper
            or "FIXTURE DETECTED" in upper
            or "DUT CONNECTED" in upper
        ):
            self.clear_error()
            self.update_operator_image("start")

        if "STOP PRESSED" in upper or "TEST ABORTED" in upper or "PRESSED STOP" in upper:
            self.set_stopped_state()

        if "FIXTURE DETECTED" in upper or "GUI:FIXTURE_CONNECTED=1" in upper:
            self.set_status(self.fixture, True)
            self.set_status(self.dut_connected, True)

        if "DUT DETECTED" in upper or "DUT CONNECTED" in upper or "GUI:DUT_INSERTED=1" in upper:
            self.set_status(self.dut_inserted, True)

        if "INSERT DUT" in upper or "DUT MISPLACED" in upper:
            self.set_status(self.dut_inserted, False)

        if "CONNECT DUT FIXTURE" in upper:
            self.set_status(self.dut_connected, False)

        if "DOOR CLOSED" in upper or "GUI:DOOR_CLOSED=1" in upper:
            self.set_status(self.door, True)

        if "CLOSE DOOR" in upper or "DOOR ERROR" in upper or "COVER OPEN" in upper:
            self.set_status(self.door, False)

        if "TYPE:FLOWMETER" in upper:
            self.dut_type_label.setText("DUT TYPE: FLOWMETER")
            self.set_status(self.dut_connected, True)
        elif "TYPE:PUMP" in upper:
            self.dut_type_label.setText("DUT TYPE: PUMP")
            self.set_status(self.dut_connected, True)
        elif "TYPE:MONOBLOCK" in upper:
            self.dut_type_label.setText("DUT TYPE: MONOBLOCK")
            self.set_status(self.dut_connected, True)
        elif "TYPE:TOPSIDE" in upper:
            self.dut_type_label.setText("DUT TYPE: TOPSIDE")
            self.set_status(self.dut_connected, True)

        if not self.error_active and ("TEST IN PROGRESS" in upper or "GUI:TEST=IN_PROGRESS" in upper):
            self.set_test_running(True)
            self.update_operator_image("in_progress")

        if "TEST PASS" in upper or "GUI:TEST=PASS" in upper:
            self.set_test_running(False)
            self.set_lamp(self.pass_lamp, "green")
            self.set_lamp(self.fail_lamp, "lightgray")
            self.clear_error()
            self.update_operator_image("passed")

        if "TEST FAIL" in upper or "GUI:TEST=FAIL" in upper:
            self.set_test_running(False)
            self.set_lamp(self.fail_lamp, "red")
            self.set_lamp(self.pass_lamp, "lightgray")
            self.clear_error()
            self.update_operator_image("failed")

        if "ERROR" in upper or "SAFETY" in upper or "WARNING" in upper:
            self.set_error(True)

        if "GUI:ERROR_CLEAR" in upper:
            self.clear_error()

    def start_pressed(self):
        if not self.fixture_ready:
            QMessageBox.warning(self, "TESTER NOT CONNECTED", "CONNECT LEAKAGE TESTER BEFORE START.")
            return

        self.start_hold_active = True
        self.serial.send("CMD:START")
        self.append_engineering_log("GUI TX: CMD:START")
        self.start_hold_timer.start()

    def start_released(self):
        self.start_hold_active = False
        self.start_hold_timer.stop()

    def send_start_hold_tick(self):
        if self.start_hold_active and self.fixture_ready:
            self.serial.send("CMD:START")

    def stop_pressed(self):
        if not self.fixture_ready:
            QMessageBox.warning(self, "TESTER NOT CONNECTED", "CONNECT LEAKAGE TESTER BEFORE STOP.")
            return

        self.stop_hold_active = True
        self.stop_long_mode = False
        self.stop_hold_delay_timer.start(800)

    def stop_released(self):
        if not self.stop_hold_active:
            return

        self.stop_hold_active = False
        self.stop_hold_delay_timer.stop()
        self.stop_hold_timer.stop()

        if self.stop_long_mode:
            self.serial.send("CMD:STOP_RELEASE")
            self.append_engineering_log("GUI TX: CMD:STOP_RELEASE")
            self.stop_long_mode = False
            return

        self.serial.send("CMD:STOP")
        self.append_engineering_log("GUI TX: CMD:STOP")
        self.set_stopped_state()

    def begin_stop_hold(self):
        if not self.stop_hold_active or not self.fixture_ready:
            return

        self.stop_long_mode = True
        self.serial.send("CMD:STOP_HOLD")
        self.append_engineering_log("GUI TX: CMD:STOP_HOLD")
        self.stop_hold_timer.start()

    def send_stop_hold_tick(self):
        if self.stop_hold_active and self.stop_long_mode and self.fixture_ready:
            self.serial.send("CMD:STOP_HOLD")

    def set_test_running(self, state):
        self.running = state
        if state and not self.error_active:
            self.run_timer.start(400)
            self.update_operator_image("in_progress")
        else:
            self.run_timer.stop()
            self.set_lamp(self.run_lamp, "lightgray")

    def set_error(self, state):
        self.error_active = state
        if state:
            self.run_timer.stop()
            self.running = False
            self.set_lamp(self.run_lamp, "lightgray")
            self.set_lamp(self.pass_lamp, "lightgray")
            self.set_lamp(self.fail_lamp, "lightgray")
            self.set_lamp(self.error_lamp, "red")
            self.update_operator_image("error")
            if not self.error_timer.isActive():
                self.error_timer.start(450)
        else:
            self.clear_error()

    def set_stopped_state(self):
        self.error_active = True
        self.running = False
        self.run_timer.stop()
        self.set_lamp(self.run_lamp, "lightgray")
        self.set_lamp(self.pass_lamp, "lightgray")
        self.set_lamp(self.fail_lamp, "lightgray")
        self.set_lamp(self.error_lamp, "red")
        self.update_operator_image("stopped")
        self.error_timer.start(450)

    def clear_error(self):
        self.error_active = False
        self.error_timer.stop()
        self.set_lamp(self.error_lamp, "lightgray")

    def blink_run_lamp(self):
        self.run_blink = not self.run_blink
        self.set_lamp(self.run_lamp, "orange" if self.run_blink else "lightgray")

    def blink_error_lamp(self):
        self.error_blink = not self.error_blink
        self.set_lamp(self.error_lamp, "red" if self.error_blink else "lightgray")
        winsound.Beep(1800, 180)

    def init_state(self):
        self.reset_all_states()
        self.instructions.setText("NO TESTER CONNECTED\nSELECT ARDUINO COM PORT\nPRESS CONNECT")

    def reset_all_states(self):
        self.set_test_running(False)
        self.clear_error()

        self.set_lamp(self.pass_lamp, "lightgray")
        self.set_lamp(self.fail_lamp, "lightgray")
        self.set_lamp(self.run_lamp, "lightgray")
        self.set_lamp(self.error_lamp, "lightgray")

        self.set_status(self.fixture, False)
        self.set_status(self.dut_inserted, False)
        self.set_status(self.door, False)
        self.set_status(self.dut_connected, False)
        self.dut_type_label.setText("DUT TYPE: --")
        self.update_operator_image("start")

    def append_engineering_log(self, text):
        display_text = text.strip().upper()
        if not display_text or display_text in self.engineering_seen_messages:
            return

        self.engineering_seen_messages.add(display_text)
        self.log.append(display_text)

    def load_operator_images(self):
        image_files = {
            "start": os.path.join("images", "start.jpg"),
            "in_progress": os.path.join("images", "inProgress.jpeg"),
            "passed": os.path.join("images", "passed.jpg"),
            "failed": os.path.join("images", "failed.png"),
            "error": os.path.join("images", "errorimage.png"),
            "stopped": os.path.join("images", "stopped.jpg"),
        }

        for key, relative in image_files.items():
            path = resource_path(relative)
            if os.path.exists(path):
                self.operator_pixmaps[key] = QPixmap(path)

        self.update_operator_image("start")

    def update_operator_image(self, key):
        self.current_operator_image = key

        if not key:
            self.operator_image.clear()
            self.operator_image.setText("")
            return

        pixmap = self.operator_pixmaps.get(key)
        if not pixmap or pixmap.isNull():
            self.operator_image.setText(key.replace("_", " ").upper())
            return

        self.operator_image.setPixmap(
            pixmap.scaled(
                self.operator_image.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
        )

    def make_small_status(self, text):
        lbl = QLabel(text)
        lbl.setFixedHeight(46)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("background:#d3d3d3; border:1px solid #222; font:bold 17px;")
        return lbl

    def make_lamp(self, text):
        lbl = QLabel(text)
        lbl.setFixedSize(125, 125)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("""
            border-radius:62px;
            background:lightgray;
            border:2px solid #111;
            font:bold 13px;
        """)
        return lbl

    def set_lamp(self, lamp, color):
        lamp.setStyleSheet(f"""
            border-radius:62px;
            background:{color};
            border:2px solid #111;
            font:bold 13px;
        """)

    def set_status(self, lbl, state):
        if state:
            lbl.setStyleSheet("background:#18a558; color:white; border:1px solid #222; font:bold 17px;")
        else:
            lbl.setStyleSheet("background:#d3d3d3; color:black; border:1px solid #222; font:bold 17px;")

    def closeEvent(self, event):
        self.serial.stop_serial()
        self.logger.close()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.current_operator_image:
            self.update_operator_image(self.current_operator_image)
