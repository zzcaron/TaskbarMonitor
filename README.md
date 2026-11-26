# 任务栏硬件与网络实时监控工具 (TaskbarMonitor)

一款轻量、高可读性、专为 Windows 10/11 任务栏设计的硬件性能与网络流速实时监控小工具。

---

## 核心特性

1. **实时多维硬件监控**
   - **网络流速**：实时上传与下载速率（KB/s、MB/s、GB/s 自适应），支持自动过滤 VPN/代理 TUN/Docker/WSL 虚拟网卡，避免网速重复翻倍。
   - **磁盘读写**：实时磁盘读取与写入速率。
   - **CPU 监控**：总体使用率与核心温度（兼容 Intel `CPU Package` 与 AMD Ryzen `Tctl/Tdie`），温度达到 75℃ 时自动高亮预警。
   - **GPU 监控**：核心利用率、核心温度与显存利用率（悬浮详情卡片展示），双显卡笔记本支持自动优先监控独立显卡。
   - **内存占用**：物理内存占用百分比与实际已用容量（GB）。

2. **高 DPI 精准对齐与双主题自适应**
   - 统一采用 Win32 物理像素计算，在 100% / 125% / 150% / 200% 缩放下均紧密贴合系统托盘左侧，不遮挡图标。
   - 支持**完全透明悬浮**与**磨砂胶囊卡片**两种外观，并自动跟随 Windows 浅色/深色任务栏主题切换配色。
   - 自动感知 `explorer.exe` 重启、任务栏自动隐藏缩起以及主屏全屏游戏/观影（副屏全屏看视频不会误隐藏主屏监控条）。

3. **原生防截屏与零干扰交互**
   - 在 Windows 10 2004+ / Windows 11 上优先启用原生 `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`，截屏时零延迟自动隐身，不入图、不闪烁。
   - 左键拖动微调水平位置、双击安全打开任务管理器、右键弹出快捷设置菜单，修改刷新频率等偏好立即热生效无需重启。

---

## 启动与打包方式

### 方式一：绿色版直接运行
前往仓库 [Releases](https://github.com/zzcaron/TaskbarMonitor/releases) 下载最新 `TaskbarMonitor.exe`，双击即可运行。

> **关于 CPU 温度读取说明**：Windows 下读取底层 CPU 核心温度传感器（MSR）通常需要管理员权限。如悬浮卡片提示未读取到 CPU 温度，可右键 `TaskbarMonitor.exe` 选择“以管理员身份运行”。

### 方式二：Python 源码运行
```bash
pip install -r requirements.txt
python main.py
```
也可直接双击 `运行软件.vbs` 或 `启动软件.bat` 静默启动（自动识别打包 exe、`.venv` 或系统 Python）。

### 方式三：自行打包 EXE
```bash
# 生成单文件独立版 dist/TaskbarMonitor.exe
python build_exe.py

# 或生成目录版 dist/TaskbarMonitor/TaskbarMonitor.exe（免解压启动更快，杀软误报更低）
python build_exe.py --onedir
```

---

## 项目结构

- `main.py`：程序主入口、单实例保护、系统托盘菜单与配置热更新装配。
- `ui_taskbar.py`：任务栏悬浮条界面、DPI 物理像素对齐、双主题配色、按需悬浮卡片与右键菜单。
- `ui_settings.py`：可视化偏好设置对话框。
- `monitor.py`：后台独立采样线程（单调时钟、可中断等待、COM 线程初始化、多显卡/AMD 温度/虚拟网卡过滤）。
- `taskbar_helper.py`：Win32 任务栏定位、原生防截屏、多屏全屏检测与自动隐藏感知。
- `config.py`：原子写入配置持久化与参数校验。
- `autostart.py`：Windows 注册表开机自启管理（带路径一致性校验）。
- `logger.py`：按大小轮转的本地日志文件模块（`%APPDATA%\TaskbarMonitor\logs\taskbar_monitor.log`）。
- `build_exe.py`：PyInstaller 一键打包脚本（支持单文件与目录模式）。
- `requirements.txt`：Python 运行与打包依赖清单。
