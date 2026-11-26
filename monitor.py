# -*- coding: utf-8 -*-
"""
硬件性能与传感器监控模块
优化点：
1. 使用 time.monotonic() 防系统校时跳变；
2. 使用 threading.Condition 替代 time.sleep，支持毫秒级优雅退出与运行时动态调整刷新频率；
3. 在 QThread 内正确执行 pythoncom.CoInitialize()/CoUninitialize() 修复 WMI 降级采集；
4. 支持多显卡自动优先独显、独立补采 GPU 温度/占用、读取显存利用率、兼容 AMD Tctl/Tdie 温度；
5. 支持智能过滤虚拟网卡（避免 VPN/TUN/Docker/WSL 造成网速翻倍）。
"""

import ctypes
import threading
import time
import psutil
from PyQt5.QtCore import QThread, pyqtSignal

from logger import get_logger

log = get_logger("monitor")

# 尝试导入 PyLibreHardwareMonitor 获取底层硬件核心温度
HAVE_LIBRE = False
try:
    from PyLibreHardwareMonitor import Computer
    HAVE_LIBRE = True
except Exception:
    Computer = None

# 尝试导入 pythoncom 以在工作线程中安全使用 WMI COM
try:
    import pythoncom
except Exception:
    pythoncom = None

# 常见虚拟网卡名称关键词（用于防止代理 TUN / 虚拟机 / Docker 导致网速重复统计）
VIRTUAL_NIC_KEYWORDS = (
    "loopback",
    "pseudo-interface",
    "vethernet",
    "hyper-v",
    "vmware",
    "virtualbox",
    "vbox",
    "docker",
    "wsl",
    "tailscale",
    "wireguard",
    "zerotier",
    "tap-windows",
    "wintun",
    "utun",
    "tunnel",
    "clash",
    "mihomo",
    "sing-box",
    "v2ray",
    "openvpn",
    "nordlynx",
    "hamachi",
    "radmin",
    "teredo",
    "isatap",
    "6to4",
    "bluetooth",
    "蓝牙",
)

# CPU 温度传感器优先级（同时覆盖 Intel Package 与 AMD Ryzen Tctl/Tdie）
CPU_TEMP_PRIORITIES = (
    "CPU Package",
    "Core (Tctl/Tdie)",
    "CPU (Tctl/Tdie)",
    "Tctl/Tdie",
    "Tdie",
    "Core Average",
    "Package",
)

# 集成显卡识别关键词（auto 模式下优先选择独立显卡）
INTEGRATED_GPU_KEYWORDS = (
    "uhd graphics",
    "hd graphics",
    "iris",
    "radeon(tm) graphics",
    "radeon graphics",
    "microsoft basic",
)


class _NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


def is_user_admin() -> bool:
    """检测当前进程是否具有 Windows 管理员权限。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def format_bytes_speed(bytes_per_sec: float) -> str:
    """格式化传输速率为易读字符串 (统一以 KB/s、MB/s、GB/s 自适应显示)。"""
    if bytes_per_sec < 0:
        bytes_per_sec = 0.0
    if bytes_per_sec < 1024 * 1024:
        return f"{bytes_per_sec / 1024:.1f} KB/s"
    if bytes_per_sec < 1024 * 1024 * 1024:
        return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
    return f"{bytes_per_sec / (1024 * 1024 * 1024):.2f} GB/s"


def is_virtual_nic(nic_name: str) -> bool:
    """判断网卡名称是否属于常见虚拟/隧道网卡。"""
    lower_name = nic_name.lower()
    return any(kw in lower_name for kw in VIRTUAL_NIC_KEYWORDS)


def select_cpu_temp(temps: dict) -> float:
    """按优先级从温度字典中提取最准确的 CPU 封装/核心温度。"""
    if not temps:
        return 0.0
    for key in CPU_TEMP_PRIORITIES:
        if key in temps and temps[key] is not None:
            val = float(temps[key])
            if 5.0 < val < 125.0:
                return val
    # 次级模糊匹配（处理带编号或本地化变体）
    for key, raw_val in temps.items():
        lk = key.lower()
        if raw_val is not None and any(tok in lk for tok in ("package", "tctl", "tdie", "average")):
            val = float(raw_val)
            if 5.0 < val < 125.0:
                return val
    # 兜底取第一个合法温度值
    for raw_val in temps.values():
        if raw_val is not None:
            val = float(raw_val)
            if 5.0 < val < 125.0:
                return val
    return 0.0


def select_primary_gpu(gpu_data: dict, preferred_mode: str = "auto"):
    """
    在多显卡环境（如笔记本核显 + 独显）中挑选主监控显卡。
    preferred_mode="auto" 时优先返回独立显卡（NVIDIA/AMD 独显/Intel Arc）。
    """
    if not gpu_data:
        return None, None
    items = list(gpu_data.items())
    if preferred_mode == "first" or len(items) == 1:
        return items[0]

    def _score_gpu(name: str) -> int:
        ln = name.lower()
        if any(k in ln for k in INTEGRATED_GPU_KEYWORDS):
            return 1
        if any(k in ln for k in ("nvidia", "geforce", "rtx", "gtx", "quadro", "radeon rx", "intel(r) arc", "intel arc", "arc(tm)")):
            return 10
        return 5

    return max(items, key=lambda pair: _score_gpu(pair[0]))


def is_matching_nvml_gpu(selected_gpu_name: str, nvml_gpu_name: str) -> bool:
    """
    判断当前选中显卡是否与 NVML 句柄（0 号 N 卡）对应同一物理设备：
    - 当未通过 LibreHardwareMonitor 识别到显卡（占位名 "GPU"）时允许由 NVML 接管；
    - 当 preferred_gpu="first" 选中 Intel/AMD 等非 NVIDIA 显卡时返回 False，
      防止将独立 N 卡的温度/占用/显存错误写入当前指标。
    """
    if not selected_gpu_name or selected_gpu_name == "GPU":
        return True
    sel = selected_gpu_name.lower().strip()
    if not any(tok in sel for tok in ("nvidia", "geforce", "quadro", "tesla", "titan")):
        return False
    if not nvml_gpu_name:
        return True
    nv = nvml_gpu_name.lower().strip()
    if sel == nv:
        return True
    sel_norm = (sel[7:] if sel.startswith("nvidia ") else sel).strip()
    nv_norm = (nv[7:] if nv.startswith("nvidia ") else nv).strip()
    if sel_norm == nv_norm:
        return True
    shorter, longer = (sel_norm, nv_norm) if len(sel_norm) <= len(nv_norm) else (nv_norm, sel_norm)
    if longer.startswith(shorter):
        rest = longer[len(shorter):].strip()
        return rest in ("laptop gpu", "gpu", "max-q", "with max-q design")
    return False


class SystemMetrics:
    """系统各项监控数据实体类"""

    def __init__(self):
        self.upload_speed = 0.0      # 上传速率 (字节/秒)
        self.download_speed = 0.0    # 下载速率 (字节/秒)
        self.disk_read_speed = 0.0   # 磁盘读取速率 (字节/秒)
        self.disk_write_speed = 0.0  # 磁盘写入速率 (字节/秒)
        self.cpu_usage = 0.0         # CPU 占用率 (%)
        self.cpu_temp = 0.0          # CPU 温度 (℃)
        self.gpu_usage = 0.0         # GPU 核心占用率 (%)
        self.gpu_mem_usage = 0.0     # GPU 显存利用率 (%)
        self.gpu_temp = 0.0          # GPU 温度 (℃)
        self.ram_usage = 0.0         # 内存占用率 (%)
        self.ram_used_gb = 0.0       # 内存已用 (GB)
        self.ram_total_gb = 0.0      # 内存总量 (GB)

        # 硬件名称与运行上下文
        self.cpu_name = "CPU"
        self.gpu_name = "GPU"
        self.is_admin = False


class MonitorWorker(QThread):
    """后台采样工作线程，支持运行时动态更新刷新间隔与网卡/显卡策略。"""

    metrics_updated = pyqtSignal(object)

    def __init__(
        self,
        interval: float = 1.0,
        filter_virtual_nics: bool = True,
        preferred_gpu: str = "auto",
        parent=None,
    ):
        super().__init__(parent)
        # 使用 Condition 统一保护配置状态与等待唤醒，彻底消除 clear/set 并发丢唤醒竞态
        self._cond = threading.Condition()
        self._stop_requested = False
        self._wake_pending = False

        self._interval = max(0.5, min(5.0, float(interval)))
        self._filter_virtual_nics = bool(filter_virtual_nics)
        self._preferred_gpu = preferred_gpu
        self._is_admin = is_user_admin()

        # 上次网络与磁盘采样基准（使用单调时钟）
        self._last_time = time.monotonic()
        self._last_net_totals = self._read_net_totals(self._filter_virtual_nics)
        self._reset_net_baseline = False
        self._last_disk = psutil.disk_io_counters()

        # 延迟到工作线程初始化的硬件探针
        self.libre_comp = None
        self._nvml = None
        self._nvml_initialized = False
        self.nvml_device = None
        self._nvml_gpu_name = ""

        # WMI 降级温度查询缓存与降频控制（负初始值确保刚开机 15 秒内也能立即首次探测）
        self._wmi_server = None
        self._wmi_last_check = -999.0
        self._wmi_unsupported = False

    def update_config(self, cfg: dict):
        """线程安全地接收设置变更，实时生效无需重启。"""
        with self._cond:
            new_interval = max(0.5, min(5.0, float(cfg.get("refresh_interval", self._interval))))
            new_filter = bool(cfg.get("filter_virtual_nics", self._filter_virtual_nics))
            new_gpu = cfg.get("preferred_gpu", self._preferred_gpu)

            interval_changed = abs(new_interval - self._interval) > 1e-6
            filter_changed = new_filter != self._filter_virtual_nics
            gpu_changed = new_gpu != self._preferred_gpu

            self._interval = new_interval
            self._filter_virtual_nics = new_filter
            self._preferred_gpu = new_gpu

            if filter_changed:
                # 仅置标志位，由工作线程在采样前同步重置基准，杜绝跨线程读写竞态
                self._reset_net_baseline = True

            if interval_changed or filter_changed or gpu_changed:
                self._wake_pending = True
                self._cond.notify_all()

    def set_interval(self, interval: float):
        """快捷调整采样间隔并立即生效。"""
        self.update_config({"refresh_interval": interval})

    def _init_hardware_probes(self):
        """在后台线程中初始化硬件驱动与传感器句柄，避免阻塞主界面启动。"""
        if HAVE_LIBRE and Computer is not None:
            try:
                self.libre_comp = Computer(IsCpuEnabled=True, IsGpuEnabled=True)
                log.info("LibreHardwareMonitor 初始化成功")
            except Exception as e:
                log.warning("初始化 LibreHardwareMonitor 失败: %s", e)
                self.libre_comp = None

        try:
            nvml_dll = ctypes.CDLL("nvml.dll")
            nvml_dll.nvmlInit_v2.argtypes = []
            nvml_dll.nvmlInit_v2.restype = ctypes.c_int
            nvml_dll.nvmlShutdown.argtypes = []
            nvml_dll.nvmlShutdown.restype = ctypes.c_int
            nvml_dll.nvmlDeviceGetHandleByIndex_v2.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
            nvml_dll.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
            nvml_dll.nvmlDeviceGetName.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint]
            nvml_dll.nvmlDeviceGetName.restype = ctypes.c_int
            nvml_dll.nvmlDeviceGetTemperature.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
            nvml_dll.nvmlDeviceGetTemperature.restype = ctypes.c_int
            nvml_dll.nvmlDeviceGetUtilizationRates.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NvmlUtilization)]
            nvml_dll.nvmlDeviceGetUtilizationRates.restype = ctypes.c_int

            if nvml_dll.nvmlInit_v2() == 0:
                self._nvml = nvml_dll
                self._nvml_initialized = True
                device = ctypes.c_void_p()
                if nvml_dll.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(device)) == 0:
                    self.nvml_device = device
                    name_buf = ctypes.create_string_buffer(96)
                    if nvml_dll.nvmlDeviceGetName(device, name_buf, 96) == 0:
                        self._nvml_gpu_name = name_buf.value.decode("utf-8", errors="ignore")
                log.info("NVML 初始化成功: %s", self._nvml_gpu_name or "NVIDIA GPU")
        except Exception:
            self._nvml = None
            self._nvml_initialized = False
            self.nvml_device = None

    def _cleanup_hardware_probes(self):
        """优雅释放 LibreHardwareMonitor、NVML 与 WMI 资源。"""
        if self.libre_comp is not None:
            for close_method in ("close", "Close"):
                fn = getattr(self.libre_comp, close_method, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
                    break
            self.libre_comp = None

        if self._nvml_initialized and self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
            self._nvml_initialized = False
            self.nvml_device = None

        self._wmi_server = None

    def _read_net_totals(self, filter_virtual: bool):
        """读取网络收发字节总数；启用过滤时剔除虚拟/TUN 网卡，防止代理模式下网速翻倍。"""
        try:
            if not filter_virtual:
                total = psutil.net_io_counters()
                return (total.bytes_sent, total.bytes_recv) if total else None

            per_nic = psutil.net_io_counters(pernic=True)
            if not per_nic:
                return None

            stats = {}
            try:
                stats = psutil.net_if_stats()
            except Exception:
                pass

            sent = 0
            recv = 0
            matched = 0
            for name, io in per_nic.items():
                if is_virtual_nic(name):
                    continue
                if stats and name in stats and not stats[name].isup:
                    continue
                sent += io.bytes_sent
                recv += io.bytes_recv
                matched += 1

            # 若系统仅有虚拟网卡在线（例如纯虚拟环境），回退到全局计数避免恒为 0
            if matched == 0:
                total = psutil.net_io_counters()
                return (total.bytes_sent, total.bytes_recv) if total else None

            return (sent, recv)
        except Exception:
            return None

    def run(self):
        com_initialized = False
        if pythoncom is not None:
            try:
                pythoncom.CoInitialize()
                com_initialized = True
            except Exception as e:
                log.warning("工作线程 COM 初始化失败: %s", e)

        try:
            self._init_hardware_probes()
            # 预热 CPU 占用率采样
            psutil.cpu_percent(interval=None)

            while True:
                with self._cond:
                    if self._stop_requested:
                        break
                    self._wake_pending = False

                loop_start = time.monotonic()
                try:
                    metrics = self._collect_metrics()
                    self.metrics_updated.emit(metrics)
                except Exception as e:
                    log.error("采样错误: %s", e)

                # 在同一把锁下检查采样期间是否收到停止/配置更新信号并等待，杜绝丢唤醒竞态
                with self._cond:
                    if self._stop_requested:
                        break
                    if self._wake_pending:
                        continue
                    elapsed = time.monotonic() - loop_start
                    wait_sec = max(0.05, self._interval - elapsed)
                    self._cond.wait_for(
                        lambda: self._stop_requested or self._wake_pending,
                        timeout=wait_sec,
                    )
                    if self._stop_requested:
                        break
        finally:
            self._cleanup_hardware_probes()
            if com_initialized and pythoncom is not None:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def stop(self):
        """毫秒级优雅停止监控工作线程。"""
        with self._cond:
            self._stop_requested = True
            self._wake_pending = True
            self._cond.notify_all()
        self.wait(2000)

    def _collect_metrics(self) -> SystemMetrics:
        """采集所有性能与温度数据。"""
        with self._cond:
            interval = self._interval
            filter_virtual = self._filter_virtual_nics
            preferred_gpu = self._preferred_gpu
            reset_net = self._reset_net_baseline
            self._reset_net_baseline = False

        if reset_net:
            self._last_net_totals = None

        now = time.monotonic()
        dt = now - self._last_time
        if dt <= 0.01:
            dt = interval

        # 检测系统休眠唤醒或挂起恢复（dt 超过正常采样间隔的 4 倍以上）
        is_waking_up = dt > max(5.0, interval * 4.0)

        metrics = SystemMetrics()
        metrics.is_admin = self._is_admin

        # 1. 网络上下行速率
        current_net = self._read_net_totals(filter_virtual)
        if current_net and self._last_net_totals:
            cur_sent, cur_recv = current_net
            last_sent, last_recv = self._last_net_totals
            if is_waking_up or cur_sent < last_sent or cur_recv < last_recv:
                metrics.upload_speed = 0.0
                metrics.download_speed = 0.0
            else:
                metrics.upload_speed = (cur_sent - last_sent) / dt
                metrics.download_speed = (cur_recv - last_recv) / dt
        self._last_net_totals = current_net

        # 2. 磁盘读写速率
        try:
            current_disk = psutil.disk_io_counters()
            if current_disk and self._last_disk:
                if (
                    is_waking_up
                    or current_disk.read_bytes < self._last_disk.read_bytes
                    or current_disk.write_bytes < self._last_disk.write_bytes
                ):
                    metrics.disk_read_speed = 0.0
                    metrics.disk_write_speed = 0.0
                else:
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

        # 4. CPU & GPU 温度与 GPU 负载/显存
        self._collect_hardware_temps(metrics, preferred_gpu)

        return metrics

    def _collect_hardware_temps(self, metrics: SystemMetrics, preferred_gpu: str):
        """采集 CPU 和 GPU 温度、核心负载及显存利用率。"""
        collected_cpu_temp = False
        collected_gpu_usage = False
        collected_gpu_temp = False
        collected_gpu_mem = False

        # 优先使用 LibreHardwareMonitor
        if self.libre_comp is not None:
            try:
                cpu_data = self.libre_comp.cpu
                if cpu_data:
                    for name, details in cpu_data.items():
                        metrics.cpu_name = name
                        temp = select_cpu_temp(details.get("Temperature", {}))
                        if temp > 0:
                            metrics.cpu_temp = temp
                            collected_cpu_temp = True
                        break

                gpu_data = self.libre_comp.gpu
                if gpu_data:
                    gpu_name, details = select_primary_gpu(gpu_data, preferred_gpu)
                    if gpu_name and details:
                        metrics.gpu_name = gpu_name
                        loads = details.get("Load", {})
                        if "GPU Core" in loads and loads["GPU Core"] is not None:
                            metrics.gpu_usage = float(loads["GPU Core"])
                            collected_gpu_usage = True
                        elif "D3D 3D" in loads and loads["D3D 3D"] is not None:
                            metrics.gpu_usage = float(loads["D3D 3D"])
                            collected_gpu_usage = True

                        if "GPU Memory" in loads and loads["GPU Memory"] is not None:
                            metrics.gpu_mem_usage = float(loads["GPU Memory"])
                            collected_gpu_mem = True

                        temps = details.get("Temperature", {})
                        if "GPU Core" in temps and temps["GPU Core"] is not None:
                            metrics.gpu_temp = float(temps["GPU Core"])
                            collected_gpu_temp = metrics.gpu_temp > 0
                        elif temps:
                            first_val = next((float(v) for v in temps.values() if v is not None), 0.0)
                            if first_val > 0:
                                metrics.gpu_temp = first_val
                                collected_gpu_temp = True
            except Exception as e:
                log.debug("LibreHardwareMonitor 采样异常: %s", e)

        # 独立补采：仅当当前显卡匹配 NVML 设备（或 LHM 未识别到显卡）时才补充缺失的 N 卡指标
        if (
            self.nvml_device is not None
            and self._nvml is not None
            and is_matching_nvml_gpu(metrics.gpu_name, self._nvml_gpu_name)
        ):
            if not (collected_gpu_usage and collected_gpu_temp and collected_gpu_mem):
                try:
                    if metrics.gpu_name == "GPU" and self._nvml_gpu_name:
                        metrics.gpu_name = self._nvml_gpu_name

                    if not collected_gpu_temp:
                        temp = ctypes.c_uint()
                        if self._nvml.nvmlDeviceGetTemperature(self.nvml_device, 0, ctypes.byref(temp)) == 0:
                            metrics.gpu_temp = float(temp.value)
                            collected_gpu_temp = metrics.gpu_temp > 0

                    if not collected_gpu_usage or not collected_gpu_mem:
                        util = _NvmlUtilization()
                        if self._nvml.nvmlDeviceGetUtilizationRates(self.nvml_device, ctypes.byref(util)) == 0:
                            if not collected_gpu_usage:
                                metrics.gpu_usage = float(util.gpu)
                            if not collected_gpu_mem:
                                metrics.gpu_mem_usage = float(util.memory)
                except Exception as e:
                    log.debug("NVML 采样异常: %s", e)

        # 若未成功获取 CPU 温度，降级查询 WMI ACPI ThermalZone（单例复用 + 15秒降频）
        if not collected_cpu_temp and not self._wmi_unsupported:
            now_t = time.monotonic()
            if now_t - self._wmi_last_check >= 15.0:
                self._wmi_last_check = now_t
                try:
                    if self._wmi_server is None:
                        import win32com.client
                        locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
                        self._wmi_server = locator.ConnectServer(".", r"root\wmi")

                    zones = self._wmi_server.ExecQuery(
                        "SELECT CurrentTemperature FROM MSAcpi_ThermalZoneTemperature"
                    )
                    has_temp = False
                    for z in zones:
                        temp_c = z.CurrentTemperature / 10.0 - 273.15
                        if 10.0 < temp_c < 115.0:
                            metrics.cpu_temp = temp_c
                            collected_cpu_temp = True
                            has_temp = True
                            break
                    if not has_temp:
                        self._wmi_unsupported = True
                except Exception as e:
                    log.debug("WMI ACPI ThermalZone 不可用: %s", e)
                    self._wmi_server = None
                    self._wmi_unsupported = True
