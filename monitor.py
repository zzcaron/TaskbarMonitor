# -*- coding: utf-8 -*-
"""
硬件性能与传感器监控模块
支持：网速(上传/下载)、硬盘(读/写)、CPU占用与温度、GPU占用与温度、内存占用
"""

import time
import psutil
from PyQt5.QtCore import QThread, pyqtSignal

# 尝试导入 PyLibreHardwareMonitor 获取底层硬件核心温度
HAVE_LIBRE = False
try:
    from PyLibreHardwareMonitor import Computer
    HAVE_LIBRE = True
except Exception:
    pass

# 尝试导入 nvml 作为 GPU 监控备选
import ctypes
HAVE_NVML = False
try:
    nvml = ctypes.CDLL('nvml.dll')
    if nvml.nvmlInit_v2() == 0:
        HAVE_NVML = True
except Exception:
    pass


def format_bytes_speed(bytes_per_sec):
    """格式化传输速率为易读字符串 (B/s, KB/s, MB/s, GB/s)"""
    if bytes_per_sec < 0:
        bytes_per_sec = 0
    if bytes_per_sec < 1024:
        return f"{int(bytes_per_sec)} B/s"
    elif bytes_per_sec < 1024 * 1024:
        return f"{bytes_per_sec / 1024:.1f} KB/s"
    elif bytes_per_sec < 1024 * 1024 * 1024:
        return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
    else:
        return f"{bytes_per_sec / (1024 * 1024 * 1024):.2f} GB/s"


class SystemMetrics:
    """系统各项监控数据实体类"""
    def __init__(self):
        self.upload_speed = 0.0      # 上传速率 (字节/秒)
        self.download_speed = 0.0    # 下载速率 (字节/秒)
        self.disk_read_speed = 0.0   # 磁盘读取速率 (字节/秒)
        self.disk_write_speed = 0.0  # 磁盘写入速率 (字节/秒)
        self.cpu_usage = 0.0         # CPU 占用率 (%)
        self.cpu_temp = 0.0          # CPU 温度 (℃)
        self.gpu_usage = 0.0         # GPU 占用率 (%)
        self.gpu_temp = 0.0          # GPU 温度 (℃)
        self.ram_usage = 0.0         # 内存占用率 (%)
        self.ram_used_gb = 0.0       # 内存已用 (GB)
        self.ram_total_gb = 0.0      # 内存总量 (GB)

        # 硬件名称信息
        self.cpu_name = "CPU"
        self.gpu_name = "GPU"


class MonitorWorker(QThread):
    """后台采样工作线程，每秒更新一次系统指标"""
    metrics_updated = pyqtSignal(object)

    def __init__(self, interval=1.0, parent=None):
        super().__init__(parent)
        self.interval = interval
        self._running = True

        # 上次网络与磁盘采样值
        self._last_time = time.time()
        self._last_net = psutil.net_io_counters()
        self._last_disk = psutil.disk_io_counters()

        # LibreHardwareMonitor 实例
        self.libre_comp = None
        if HAVE_LIBRE:
            try:
                self.libre_comp = Computer(IsCpuEnabled=True, IsGpuEnabled=True)
            except Exception as e:
                print(f"[监控模块] 初始化 LibreHardwareMonitor 失败: {e}")

        # NVML 设备句柄（如果存在）
        self.nvml_device = None
        if HAVE_NVML:
            try:
                device = ctypes.c_void_p()
                if nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(device)) == 0:
                    self.nvml_device = device
            except Exception:
                pass

    def run(self):
        # 预热 CPU 占用率采样
        psutil.cpu_percent(interval=None)

        while self._running:
            try:
                metrics = self._collect_metrics()
                self.metrics_updated.emit(metrics)
            except Exception as e:
                print(f"[监控模块] 采样错误: {e}")
            time.sleep(self.interval)

    def stop(self):
        """停止监控工作线程"""
        self._running = False
        self.wait(2000)

    def _collect_metrics(self):
        """采集所有性能与温度数据"""
        now = time.time()
        dt = now - self._last_time
        if dt <= 0:
            dt = 1.0

        metrics = SystemMetrics()

        # 1. 网络上下行速率
        try:
            current_net = psutil.net_io_counters()
            metrics.upload_speed = (current_net.bytes_sent - self._last_net.bytes_sent) / dt
            metrics.download_speed = (current_net.bytes_recv - self._last_net.bytes_recv) / dt
            self._last_net = current_net
        except Exception:
            pass

        # 2. 磁盘读写速率
        try:
            current_disk = psutil.disk_io_counters()
            if current_disk and self._last_disk:
                metrics.disk_read_speed = (current_disk.read_bytes - self._last_disk.read_bytes) / dt
                metrics.disk_write_speed = (current_disk.write_bytes - self._last_disk.write_bytes) / dt
            self._last_disk = current_disk
        except Exception:
            pass

        self._last_time = now

        # 3. CPU 占用率与内存占用
        try:
            metrics.cpu_usage = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            metrics.ram_usage = mem.percent
            metrics.ram_used_gb = mem.used / (1024 ** 3)
            metrics.ram_total_gb = mem.total / (1024 ** 3)
        except Exception:
            pass

        # 4. CPU & GPU 温度与 GPU 占用率
        self._collect_hardware_temps(metrics)

        return metrics

    def _collect_hardware_temps(self, metrics):
        """采集 CPU 和 GPU 温度及负载"""
        collected_cpu_temp = False
        collected_gpu = False

        # 优先使用 LibreHardwareMonitor
        if self.libre_comp:
            try:
                # 获取 CPU 信息
                cpu_data = self.libre_comp.cpu
                if cpu_data:
                    for name, details in cpu_data.items():
                        metrics.cpu_name = name
                        temps = details.get('Temperature', {})
                        # 优先取 Package 温度，其次取 Core Average 或第一个核心温度
                        if 'CPU Package' in temps:
                            metrics.cpu_temp = float(temps['CPU Package'])
                            collected_cpu_temp = True
                        elif 'Core Average' in temps:
                            metrics.cpu_temp = float(temps['Core Average'])
                            collected_cpu_temp = True
                        elif temps:
                            metrics.cpu_temp = float(next(iter(temps.values())))
                            collected_cpu_temp = True
                        break

                # 获取 GPU 信息
                gpu_data = self.libre_comp.gpu
                if gpu_data:
                    for name, details in gpu_data.items():
                        metrics.gpu_name = name
                        # GPU 负载
                        loads = details.get('Load', {})
                        if 'GPU Core' in loads:
                            metrics.gpu_usage = float(loads['GPU Core'])
                            collected_gpu = True
                        elif 'D3D 3D' in loads:
                            metrics.gpu_usage = float(loads['D3D 3D'])
                            collected_gpu = True

                        # GPU 温度
                        temps = details.get('Temperature', {})
                        if 'GPU Core' in temps:
                            metrics.gpu_temp = float(temps['GPU Core'])
                        elif temps:
                            metrics.gpu_temp = float(next(iter(temps.values())))
                        break
            except Exception as e:
                pass

        # 若未成功获取 GPU，尝试使用 NVML 原生接口
        if not collected_gpu and self.nvml_device:
            try:
                # 获取 GPU 温度
                temp = ctypes.c_uint()
                if nvml.nvmlDeviceGetTemperature(self.nvml_device, 0, ctypes.byref(temp)) == 0:
                    metrics.gpu_temp = float(temp.value)

                # 获取 GPU 负载
                class Utilization(ctypes.Structure):
                    _fields_ = [('gpu', ctypes.c_uint), ('memory', ctypes.c_uint)]
                util = Utilization()
                if nvml.nvmlDeviceGetUtilizationRates(self.nvml_device, ctypes.byref(util)) == 0:
                    metrics.gpu_usage = float(util.gpu)
            except Exception:
                pass

        # 若未成功获取 CPU 温度，尝试降级查询 WMI ACPI ThermalZone
        if not collected_cpu_temp:
            try:
                import win32com.client
                locator = win32com.client.Dispatch('WbemScripting.SWbemLocator')
                server = locator.ConnectServer('.', 'root\\wmi')
                zones = server.ExecQuery('SELECT CurrentTemperature FROM MSAcpi_ThermalZoneTemperature')
                for z in zones:
                    temp_c = z.CurrentTemperature / 10.0 - 273.15
                    if 10.0 < temp_c < 115.0:
                        metrics.cpu_temp = temp_c
                        break
            except Exception:
                pass
