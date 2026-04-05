import sys
import os
import psutil
import time
import threading
import numpy as np
from collections import deque
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import warnings
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QVBoxLayout, QHBoxLayout, 
    QWidget, QFrame, QTextEdit, QPushButton, QMessageBox, QTableWidget, 
    QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PyQt6.QtGui import QFont, QPainter, QColor, QPen
from PyQt6.QtCore import QTimer, Qt, QRectF
import pyqtgraph as pg

warnings.filterwarnings("ignore", category=UserWarning)
class AnomalyDetector:
    def __init__(self, window_size=300, detection_interval=5):
        self.window_size = window_size
        self.detection_interval = detection_interval
        self.latest_status = None 
        self.last_overhead_ms = 0.0 
        self.last_raw_score = 0.0
        
        self.data_window = deque(maxlen=window_size)
        self.is_running = False
        self.thread = None
        self._last_disk_io = psutil.disk_io_counters()
        psutil.cpu_percent(interval=None)

    def _get_metrics(self):
        try:
            global_cpu = psutil.cpu_percent(interval=0.1)
            mem_data = psutil.virtual_memory()
            my_process = psutil.Process(os.getpid())
            my_cpu = my_process.cpu_percent(interval=None) / psutil.cpu_count()
            my_mem_bytes = my_process.memory_info().rss
            adjusted_cpu = max(0.0, global_cpu - my_cpu)
            adjusted_mem_percent = max(0.0, ((mem_data.used - my_mem_bytes) / mem_data.total) * 100)
            current_disk_io = psutil.disk_io_counters()
            read_bytes = current_disk_io.read_bytes - self._last_disk_io.read_bytes
            write_bytes = current_disk_io.write_bytes - self._last_disk_io.write_bytes
            self._last_disk_io = current_disk_io
            
            return [adjusted_cpu, adjusted_mem_percent, float(read_bytes), float(write_bytes)]
        except Exception:
            return [0.0, 0.0, 0.0, 0.0]

    def _loop(self):
        counter = 0
        while self.is_running:
            metrics = self._get_metrics()
            self.data_window.append(metrics)
            if counter > 0 and counter % self.detection_interval == 0:
                if len(self.data_window) >= 30:
                    self._detect_anomaly()
            
            counter += 1
            time.sleep(1)

    def _detect_anomaly(self):
        try:
            start_time = time.perf_counter()
            data_buf = np.array(list(self.data_window))
            scaler = StandardScaler()
            data_scaled = scaler.fit_transform(data_buf)
            model = IsolationForest(n_estimators=100, contamination=0.05, random_state=42)
            model.fit(data_scaled)
            current_point = data_buf[-1].reshape(1, -1)
            current_scaled = scaler.transform(current_point)
            
            prediction = model.predict(current_scaled)
            decision_score = model.decision_function(current_scaled)[0]
            self.last_raw_score = decision_score
            
            is_outlier = (prediction[0] == -1)
            median_cpu = np.median(data_buf[:, 0])
            median_ram = np.median(data_buf[:, 1])
            is_spiking = (current_point[0][0] > median_cpu) or (current_point[0][1] > median_ram)
            
            self.latest_status = bool(is_outlier and is_spiking)
            
            self.last_overhead_ms = (time.perf_counter() - start_time) * 1000
        except Exception:
            pass

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=2)

class DevModeTracker:
    TARGET_PROCESSES = {'code.exe', 'idea64.exe', 'docker.exe', 'python.exe', 'java.exe'}

    def __init__(self):
        self._last_io_cache = {}
        psutil.cpu_percent(interval=None)

    def get_stats(self):
        total_cpu = psutil.cpu_percent(interval=None)
        total_mem_mb = psutil.virtual_memory().used / (1024 * 1024)
        
        target_stats = {"cpu_percent": 0.0, "memory_mb": 0.0}

        for proc in psutil.process_iter(['name', 'pid', 'memory_info']):
            try:
                if proc.info['name'] and proc.info['name'].lower() in [n.lower() for n in self.TARGET_PROCESSES]:
                    with proc.oneshot():
                        target_stats["cpu_percent"] += proc.cpu_percent(interval=None)
                        if proc.info['memory_info']:
                            target_stats["memory_mb"] += proc.info['memory_info'].rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        ros_cpu = max(0.0, total_cpu - (target_stats["cpu_percent"] / psutil.cpu_count()))
        ros_mem = max(0.0, total_mem_mb - target_stats["memory_mb"])

        sys_mem_total = psutil.virtual_memory().total / (1024*1024)
        return {
            "target_cpu": min(100, target_stats["cpu_percent"] / psutil.cpu_count()),
            "target_mem": min(100, (target_stats["memory_mb"] / sys_mem_total) * 100),
            "sys_cpu": min(100, ros_cpu),
            "sys_mem": min(100, (ros_mem / sys_mem_total) * 100)
        }
    
class CircularGauge(QWidget):
    def __init__(self, title, max_val=100, unit="MB/s"):
        super().__init__()
        self.title = title
        self.value = 0
        self.max_val = max_val
        self.unit = unit
        self.color = QColor("#4DA8DA") 
        self.setMinimumSize(120, 120)
    
    def set_value(self, val):
        self.value = val
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = QRectF(10, 10, self.width() - 20, self.height() - 20)
        
        pen = QPen(QColor("#2B2E33"), 6)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)
        
        pen.setColor(self.color)
        display_val = min(self.value, self.max_val)
        span_angle = int((display_val / self.max_val) * -360 * 16)
        painter.setPen(pen)
        painter.drawArc(rect, 270 * 16, span_angle)
        
        painter.setPen(QColor("#E0E0E0"))
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        painter.drawText(self.rect().adjusted(0, -10, 0, 0), Qt.AlignmentFlag.AlignCenter, f"{self.value:.1f}")
        
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(self.rect().adjusted(0, 15, 0, 0), Qt.AlignmentFlag.AlignCenter, self.unit)
        
        painter.setPen(QColor("#8A9199"))
        painter.drawText(self.rect().adjusted(0, 45, 0, 0), Qt.AlignmentFlag.AlignCenter, self.title)

class StatusPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        
        self.title_label = QLabel("SYSTEM ML TELEMETRY")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 12px; color: #8A9199; letter-spacing: 1px;")
        
        self.status_label = QLabel("INITIALIZING BASELINE...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.status_label.setStyleSheet("font-size: 18px; font-weight: 600; color: #FFFFFF;")
        
        layout.addWidget(self.title_label)
        layout.addWidget(self.status_label)
        
        self.terminal_log = QTextEdit()
        self.terminal_log.setReadOnly(True)
        self.terminal_log.setStyleSheet("""
            background: #1E1E1E; color: #D4D4D4; 
            font-family: Consolas, monospace; font-size: 11px; 
            border: 1px solid #333333; padding: 5px;
        """)
        self.terminal_log.setFixedHeight(110)
        self.terminal_log.append("> Anomaly Detection Engine: Online")
        self.terminal_log.append("> Awaiting telemetry baseline...")
        layout.addWidget(self.terminal_log)

        self.setStyleSheet("background: #252526; border: 1px solid #333333; border-radius: 4px; padding: 5px;")

    def set_anomaly(self, is_anomaly, overhead_ms):
        timestamp = time.strftime('%H:%M:%S')
        if is_anomaly:
            self.status_label.setText("STATE: ANOMALY DETECTED")
            self.status_label.setStyleSheet("font-size: 18px; font-weight: 600; color: #E06C75;") 
            self.terminal_log.append(f"[{timestamp}] WARNING: Distribution deviation detected.")
        else:
            self.status_label.setText("STATE: NOMINAL")
            self.status_label.setStyleSheet("font-size: 18px; font-weight: 600; color: #98C379;") 
            self.terminal_log.append(f"[{timestamp}] INFO: System nominal. (ML Overhead: {overhead_ms:.1f}ms)")
        
        self.terminal_log.verticalScrollBar().setValue(self.terminal_log.verticalScrollBar().maximum())

class SystemMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Research Prototype: ML-Enhanced System Telemetry")
        self.setGeometry(100, 100, 1400, 950)
        self.setStyleSheet("background-color: #1E1E1E; color: #D4D4D4; font-family: 'Segoe UI';")

        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QVBoxLayout(self.main_widget)
        self.main_layout.setSpacing(15)
        self.top_row = QHBoxLayout()
        
        self.health_panel = StatusPanel()
        self.top_row.addWidget(self.health_panel, 1)

        self.process_panel = QWidget()
        proc_layout = QVBoxLayout(self.process_panel)
        proc_layout.setContentsMargins(0,0,0,0)
        
        proc_header = QLabel("TOP 10 PROCESSES (BY MEMORY ALLOCATION)")
        proc_header.setStyleSheet("font-weight: bold; font-size: 12px; color: #8A9199;")
        proc_layout.addWidget(proc_header)

        self.process_table = QTableWidget(10, 3)
        self.process_table.setHorizontalHeaderLabels(["PID", "Process Name", "Memory (MB)"])
        self.process_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.process_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.process_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.process_table.setStyleSheet("""
            QTableWidget { background-color: #252526; color: #D4D4D4; gridline-color: #333333; border: 1px solid #333333; }
            QHeaderView::section { background-color: #333333; color: #FFFFFF; font-weight: bold; border: none; padding: 4px; }
        """)
        proc_layout.addWidget(self.process_table)

        self.btn_kill_selected = QPushButton("Terminate Selected PID")
        self.btn_kill_selected.setStyleSheet("""
            QPushButton { background: #3E4451; color: white; padding: 6px; border-radius: 3px; font-weight: bold; }
            QPushButton:hover { background: #E06C75; }
        """)
        self.btn_kill_selected.clicked.connect(self.kill_selected_process)
        proc_layout.addWidget(self.btn_kill_selected)

        self.top_row.addWidget(self.process_panel, 2)
        self.main_layout.addLayout(self.top_row)
        self.mid_row = QHBoxLayout()
        
        self.gauges_frame = QFrame()
        self.gauges_frame.setStyleSheet("background: #252526; border: 1px solid #333333; border-radius: 4px;")
        gauges_layout = QHBoxLayout(self.gauges_frame)
        
        self.gauge_net_dl = CircularGauge("NET IN", max_val=50) 
        self.gauge_net_ul = CircularGauge("NET OUT", max_val=20)
        self.gauge_disk_r = CircularGauge("DISK READ", max_val=100)
        
        gauges_layout.addWidget(self.gauge_net_dl)
        gauges_layout.addWidget(self.gauge_net_ul)
        gauges_layout.addWidget(self.gauge_disk_r)
        self.mid_row.addWidget(self.gauges_frame, 1)

        self.cost_frame = QFrame()
        self.cost_frame.setStyleSheet("background: #252526; border: 1px solid #333333; border-radius: 4px;")
        cost_layout = QVBoxLayout(self.cost_frame)
        cost_label = QLabel("TARGET WORKLOAD ISOLATION (%)")
        cost_label.setStyleSheet("font-weight: bold; font-size: 12px; color: #8A9199; padding-left: 5px;")
        cost_layout.addWidget(cost_label)
        
        self.cost_chart = pg.PlotWidget()
        self.cost_chart.setBackground('#252526')
        self.cost_chart.showGrid(x=False, y=True, alpha=0.3)
        self.cost_chart.setYRange(0, 100)
        self.cost_chart.getAxis('bottom').setTicks([[(0.5, 'CPU'), (1.5, 'MEM')]])
        
        self.dev_bars = pg.BarGraphItem(x=[0.35, 1.35], height=[0, 0], width=0.3, brush='#4DA8DA', name='Target Runtimes')
        self.sys_bars = pg.BarGraphItem(x=[0.65, 1.65], height=[0, 0], width=0.3, brush='#3E4451', name='System OS')
        self.cost_chart.addItem(self.dev_bars)
        self.cost_chart.addItem(self.sys_bars)
        cost_layout.addWidget(self.cost_chart)
        self.mid_row.addWidget(self.cost_frame, 1)
        
        self.main_layout.addLayout(self.mid_row)

        # --- Bottom Row: CPU Timeline ---
        self.cpu_frame = QFrame()
        self.cpu_frame.setStyleSheet("background: #252526; border: 1px solid #333333; border-radius: 4px;")
        cpu_layout = QVBoxLayout(self.cpu_frame)
        cpu_label = QLabel("GLOBAL CPU ALLOCATION TIMELINE")
        cpu_label.setStyleSheet("font-weight: bold; font-size: 12px; color: #8A9199; padding-left: 5px;")
        cpu_layout.addWidget(cpu_label)

        self.cpu_usage_graph = pg.PlotWidget()
        self.cpu_usage_graph.setBackground('#252526')
        self.cpu_usage_graph.showGrid(x=True, y=True, alpha=0.2)
        self.cpu_usage_plot = self.cpu_usage_graph.plot(pen=pg.mkPen(color='#98C379', width=2))
        cpu_layout.addWidget(self.cpu_usage_graph)
        self.main_layout.addWidget(self.cpu_frame)
        self.footer = QHBoxLayout()
        self.stat_procs = QLabel("Total Processes: 0")
        self.stat_threads = QLabel("Total Threads: 0")
        self.stat_cpu = QLabel("Logical Cores: 0")
        
        for lbl in [self.stat_procs, self.stat_threads, self.stat_cpu]:
            lbl.setStyleSheet("font-size: 11px; color: #8A9199;")
            self.footer.addWidget(lbl)
        self.main_layout.addLayout(self.footer)
        self.dev_tracker = DevModeTracker()
        self.anomaly_detector = AnomalyDetector(window_size=300, detection_interval=5)
        self.anomaly_detector.start()
        
        self.prev_ml_status = None
        self.last_net_io = psutil.net_io_counters()
        self.last_disk_io = psutil.disk_io_counters()
        self.cpu_usage_data = []
        self.time_data = []

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_metrics)
        self.timer.start(1000) 

    def update_metrics(self):
        try:
            current_ml_status = self.anomaly_detector.latest_status
            overhead = self.anomaly_detector.last_overhead_ms
            
            if current_ml_status is not None and current_ml_status != self.prev_ml_status:
                self.health_panel.set_anomaly(current_ml_status, overhead)
                self.prev_ml_status = current_ml_status
            stats = self.dev_tracker.get_stats()
            self.dev_bars.setOpts(height=[stats['target_cpu'], stats['target_mem']])
            self.sys_bars.setOpts(height=[stats['sys_cpu'], stats['sys_mem']])
            curr_net = psutil.net_io_counters()
            curr_disk = psutil.disk_io_counters()
            
            self.gauge_net_dl.set_value((curr_net.bytes_recv - self.last_net_io.bytes_recv) / 1048576)
            self.gauge_net_ul.set_value((curr_net.bytes_sent - self.last_net_io.bytes_sent) / 1048576)
            self.gauge_disk_r.set_value((curr_disk.read_bytes - self.last_disk_io.read_bytes) / 1048576)
            
            self.last_net_io, self.last_disk_io = curr_net, curr_disk
            self.update_process_table()
            cpu_usage = psutil.cpu_percent(interval=None)
            self.cpu_usage_data.append(cpu_usage)
            self.time_data.append(time.time())
            if len(self.cpu_usage_data) > 60:
                self.cpu_usage_data.pop(0)
                self.time_data.pop(0)
            self.cpu_usage_plot.setData(self.time_data, self.cpu_usage_data)
            self.stat_procs.setText(f"Total Processes: {len(psutil.pids())}")
            self.stat_cpu.setText(f"Logical Cores: {psutil.cpu_count()}")
            csv_filename = "research_results.csv"
            write_header = not os.path.exists(csv_filename)
            
            with open(csv_filename, "a") as f:
                if write_header:
                    f.write("Timestamp,CPU_Usage,RAM_Usage,Anomaly_Score,Is_Anomaly\n")
                
                ml_int = 1 if current_ml_status else 0
                raw_score = self.anomaly_detector.last_raw_score
                f.write(f"{time.time()},{cpu_usage},{psutil.virtual_memory().percent},{raw_score},{ml_int}\n")

        except Exception as e:
            pass

    def update_process_table(self):
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                if p.info['memory_info']:
                    procs.append((p.info['pid'], p.info['name'], p.info['memory_info'].rss))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        procs.sort(key=lambda x: x[2], reverse=True)
        top_10 = procs[:10]

        for row, (pid, name, mem) in enumerate(top_10):
            self.process_table.setItem(row, 0, QTableWidgetItem(str(pid)))
            self.process_table.setItem(row, 1, QTableWidgetItem(name))
            self.process_table.setItem(row, 2, QTableWidgetItem(f"{mem / 1048576:.1f}"))

    def kill_selected_process(self):
        selected_items = self.process_table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Selection Error", "Please select a process from the table to terminate.")
            return
        
        row = selected_items[0].row()
        pid_item = self.process_table.item(row, 0)
        name_item = self.process_table.item(row, 1)
        
        if pid_item:
            try:
                pid = int(pid_item.text())
                name = name_item.text() if name_item else "Unknown"
                proc = psutil.Process(pid)
                proc.terminate()
                QMessageBox.information(self, "Success", f"Termination signal sent to PID {pid} ({name}).")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to terminate PID {pid}: {str(e)}")

    def closeEvent(self, event):
        self.anomaly_detector.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    monitor = SystemMonitor()
    monitor.show()
    sys.exit(app.exec())