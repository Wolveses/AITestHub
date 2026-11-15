# -*- coding: utf-8 -*-
"""
应用枚举器（仅支持 Android）
负责枚举 Android 设备上安装的应用
"""

import re
from typing import List, Optional
from abc import ABC, abstractmethod
from logzero import logger

from .models import AppInfo, AppStatus, Platform


class BaseAppEnumerator(ABC):
    """
    应用枚举器基类
    定义所有应用枚举器必须实现的接口
    """

    def __init__(self, device_id: str):
        """
        初始化应用枚举器

        Args:
            device_id: 设备ID
        """
        self.device_id = device_id
        self._cached_apps: List[AppInfo] = []

    @abstractmethod
    def enumerate_apps(self, include_system_apps: bool = False) -> List[AppInfo]:
        """
        枚举设备上的所有应用

        Args:
            include_system_apps: 是否包含系统应用

        Returns:
            List[AppInfo]: 应用信息列表
        """
        pass

    @abstractmethod
    def get_running_apps(self) -> List[AppInfo]:
        """
        获取正在运行的应用列表

        Returns:
            List[AppInfo]: 运行中的应用列表
        """
        pass

    @abstractmethod
    def get_app_info(self, package_name: str) -> Optional[AppInfo]:
        """
        获取指定应用的详细信息

        Args:
            package_name: 包名（Android）

        Returns:
            AppInfo: 应用信息，未找到返回None
        """
        pass

    def filter_apps(
        self, apps: List[AppInfo], keyword: str = None, running_only: bool = False
    ) -> List[AppInfo]:
        """
        过滤应用列表

        Args:
            apps: 应用列表
            keyword: 搜索关键字（匹配应用名称或包名）
            running_only: 是否只显示运行中的应用

        Returns:
            List[AppInfo]: 过滤后的应用列表
        """
        filtered = apps

        # 按运行状态过滤
        if running_only:
            filtered = [app for app in filtered if app.is_running]

        # 按关键字过滤
        if keyword and keyword.strip():
            keyword_lower = keyword.lower()
            filtered = [
                app
                for app in filtered
                if keyword_lower in app.app_name.lower()
                or keyword_lower in app.package_name.lower()
            ]

        return filtered


class AndroidAppEnumerator(BaseAppEnumerator):
    """
    Android应用枚举器
    通过ADB获取Android设备上的应用信息
    """

    def __init__(self, device_id: str):
        """
        初始化Android应用枚举器

        Args:
            device_id: Android设备ID
        """
        super().__init__(device_id)
        self._adb = None
        self._init_adb()

    def _init_adb(self):
        """初始化ADB连接"""
        try:
            from insight_aitest.platform.services.collectors.adb import adb

            self._adb = adb
            logger.info(f"Android应用枚举器初始化成功: {self.device_id}")
        except Exception as e:
            logger.error(f"初始化ADB失败: {e}")
            self._adb = None

    def enumerate_apps(self, include_system_apps: bool = False) -> List[AppInfo]:
        """
        枚举Android设备上的所有应用

        Args:
            include_system_apps: 是否包含系统应用

        Returns:
            List[AppInfo]: 应用信息列表
        """
        try:
            if not self._adb:
                return []

            # 获取应用列表 - 使用 -3 参数只获取第三方应用
            cmd = "pm list packages"
            if not include_system_apps:
                cmd += " -3"  # 只显示第三方应用

            output = self._adb.shell(cmd, self.device_id, timeout=30)
            if not output:
                return []

            # 解析应用列表
            apps = []
            for line in output.split("\n"):
                line = line.strip()
                if line.startswith("package:"):
                    package_name = line.replace("package:", "").strip()

                    # 直接使用包名作为应用名称（专业工具面向专业测试人员）
                    app_info = AppInfo(
                        package_name=package_name,
                        app_name=package_name,  # 直接使用包名
                        pid=None,
                        is_running=False,
                        status=AppStatus.STOPPED,
                        uid=None,
                        version=None,
                    )
                    apps.append(app_info)

            self._cached_apps = apps
            logger.info(f"枚举Android应用完成: {len(apps)}个应用")
            return apps

        except Exception as e:
            logger.error(f"枚举Android应用失败: {e}")
            return []

    def _get_app_version(self, package_name: str) -> Optional[str]:
        """获取应用版本"""
        try:
            output = self._adb.shell(f"dumpsys package {package_name}", self.device_id, timeout=10)
            if output:
                # 使用 Python 解析而不是 grep
                for line in output.split("\n"):
                    if "versionName=" in line:
                        match = re.search(r"versionName=([\d.]+)", line)
                        if match:
                            return match.group(1)
            return None
        except Exception:
            return None

    def _get_app_details(self, package_name: str) -> Optional[AppInfo]:
        """
        获取应用详细信息

        Args:
            package_name: 包名

        Returns:
            AppInfo: 应用信息
        """
        try:
            # 创建基本信息，不执行额外的ADB命令以提高性能
            app_info = AppInfo(
                package_name=package_name,
                app_name=self._format_package_name(package_name),
                pid=None,
                is_running=False,
                status=AppStatus.STOPPED,
                uid=None,
                version=None,
            )
            return app_info
        except Exception as e:
            logger.error(f"获取应用详情失败: {package_name}, {e}")
            return None

    def _get_app_name(self, package_name: str) -> Optional[str]:
        """获取应用显示名称（已弃用，使用_format_package_name代替）"""
        return self._format_package_name(package_name)

    def _format_package_name(self, package_name: str) -> str:
        """
        格式化包名为应用显示名称
        对于专业工具，直接使用包名作为应用名称
        """
        return package_name

    def _get_app_uid(self, package_name: str) -> Optional[int]:
        """获取应用UID"""
        try:
            output = self._adb.shell(f"dumpsys package {package_name}", self.device_id, timeout=10)
            if output:
                # 使用 Python 解析而不是 grep
                for line in output.split("\n"):
                    if "userId=" in line:
                        match = re.search(r"userId=(\d+)", line)
                        if match:
                            return int(match.group(1))
            return None
        except Exception:
            return None

    def _is_app_running(self, package_name: str) -> bool:
        """检查应用是否正在运行"""
        try:
            output = self._adb.shell(f"pidof {package_name}", self.device_id, timeout=5)
            return output.strip() != ""
        except Exception:
            return False

    def _get_app_pid(self, package_name: str) -> Optional[int]:
        """获取应用进程ID"""
        try:
            output = self._adb.shell(f"pidof {package_name}", self.device_id, timeout=5)
            if output.strip():
                pids = output.strip().split()
                return int(pids[0]) if pids else None
            return None
        except Exception:
            return None

    def get_running_apps(self) -> List[AppInfo]:
        """
        获取正在运行的Android应用

        Returns:
            List[AppInfo]: 运行中的应用列表
        """
        try:
            if not self._adb:
                return []

            # 获取进程优先级信息（用于判断是否在前台）
            process_priority = self._get_process_priorities()

            # 如果通过 dumpsys activity processes 没有找到任何前台进程，
            # 尝试使用备用方法
            if not any(info["is_foreground"] for info in process_priority.values()):
                logger.warning("未通过 dumpsys activity processes 检测到前台进程，尝试备用方法")
                process_priority = self._get_process_priorities_fallback()

            # 使用ps命令获取所有进程（兼容 OPPO/ColorOS 等带 FRZ 列的 10 列 ps -A 输出，以及旧版 ps）
            output = self._adb.shell("ps -A", self.device_id, timeout=10)
            if not output or len(output.strip().splitlines()) <= 1:
                output = self._adb.shell("ps", self.device_id, timeout=10)
            if not output:
                return []

            # 解析进程列表
            running_apps = {}
            for line in output.split("\n")[1:]:  # 跳过标题行
                parts = line.split()
                if len(parts) >= 3 and parts[1].isdigit():
                    pid = int(parts[1])
                    raw_name = parts[-1]
                    package_name = raw_name.split(":")[0]

                    # 只关注包含包名格式的应用进程
                    if "." in package_name and not package_name.startswith("."):
                        is_main_process = raw_name == package_name
                        if package_name not in running_apps or is_main_process:
                            running_apps[package_name] = {
                                "pid": pid,
                                "package_name": package_name,
                                "is_foreground": False,  # 默认非前台
                            }

            # 更新前台状态
            for package_name in running_apps:
                if package_name in process_priority:
                    running_apps[package_name]["is_foreground"] = process_priority[package_name][
                        "is_foreground"
                    ]
                    running_apps[package_name]["oom_adj"] = process_priority[package_name].get(
                        "oom_adj", 1000
                    )

            # 转换为AppInfo列表
            apps = []
            for package_name, proc_info in running_apps.items():
                app_info = self._get_app_details(package_name)
                if app_info:
                    # 所有存在的进程都标记为运行中（包括后台进程）
                    app_info.is_running = True
                    app_info.pid = proc_info["pid"]
                    # 根据前台状态设置不同的应用状态
                    if proc_info["is_foreground"]:
                        app_info.status = AppStatus.RUNNING
                    else:
                        app_info.status = AppStatus.BACKGROUND  # 后台运行状态
                    apps.append(app_info)

            logger.info(
                f"应用状态检测完成: 总计 {len(apps)} 个应用，前台: {sum(1 for a in apps if a.status == AppStatus.RUNNING)}，后台: {sum(1 for a in apps if a.status == AppStatus.BACKGROUND)}"
            )
            return apps

        except Exception as e:
            logger.error(f"获取运行中的Android应用失败: {e}")
            return []

    def _get_process_priorities(self) -> dict:
        """
        获取进程优先级信息
        使用 dumpsys activity processes 获取 oom_adj 值

        Returns:
            dict: {package_name: {'is_foreground': bool, 'oom_adj': int}}
        """
        try:
            output = self._adb.shell("dumpsys activity processes", self.device_id, timeout=10)
            if not output:
                return {}

            process_info = {}
            current_package = None

            # 调试：保存完整输出到日志文件
            logger.debug(f"dumpsys activity processes 输出长度: {len(output)} 字符")

            for line in output.split("\n"):
                stripped = line.strip()

                # 查找进程块起始行：
                # 1) Android 8+ 格式: *APP* UID 10029 ProcessRecord{85a5ab2 2742:com.digibird.umplayer/u0a29}
                # 2) 旧格式: Process Record{... u0 com.xlive.app/pid:1234...}
                match_modern = re.search(
                    r"\*(?:APP|PERS)\*\s+UID\s+\d+\s+ProcessRecord\{[^\s]+\s+(\d+):([\w.\-:]+)/",
                    line,
                )
                match_legacy = re.search(r"u0\s+([\w.]+)/.*pid:(\d+)", line)

                if match_modern or match_legacy:
                    if match_modern:
                        current_pid = int(match_modern.group(1))
                        current_package = match_modern.group(2).split(":")[0]
                    else:
                        current_package = match_legacy.group(1)
                        current_pid = int(match_legacy.group(2))

                    if current_package not in process_info:
                        process_info[current_package] = {
                            "is_foreground": False,
                            "oom_adj": 1000,  # 默认后台优先级
                        }
                    logger.debug(f"找到进程: {current_package} (PID: {current_pid})")
                    continue

                # 遇到汇总列表行或非进程块标题时重置 current_package，避免后续属性误归属
                if current_package and (
                    stripped.startswith("PID #")
                    or stripped.startswith("Proc #")
                    or "ProcessRecord{" in line
                    or "Process Record{" in line
                ):
                    current_package = None
                    continue

                if not current_package:
                    continue

                # Android 8+ 进程块中的前台标记与 oom 分值：
                # oom: max=1001 curRaw=0 setRaw=0 cur=0 set=0
                # hasClientActivities=false foregroundActivities=true (rep=true)
                if "foregroundActivities=true" in line:
                    process_info[current_package]["is_foreground"] = True
                    process_info[current_package]["oom_adj"] = min(
                        process_info[current_package]["oom_adj"], 0
                    )
                    logger.info(f"标记为前台: {current_package} (foregroundActivities=true)")

                oom_match = re.search(r"\boom:.*\bcur=(-?\d+)", line)
                if oom_match:
                    cur_adj = int(oom_match.group(1))
                    process_info[current_package]["oom_adj"] = cur_adj
                    if cur_adj == 0:
                        process_info[current_package]["is_foreground"] = True
                        logger.info(f"标记为前台: {current_package} (oom cur={cur_adj})")

                # 兼容旧格式 adj= 值
                if "adj=" in line:
                    # 例如：adj=_FOREGROUND_APP 或 adj=0
                    adj_match = re.search(r"adj=(\S+)", line)
                    if adj_match:
                        adj_value = adj_match.group(1)
                        logger.debug(f"包名 {current_package} 的 adj={adj_value}")

                        is_fg = adj_value in [
                            "_FOREGROUND_APP",
                            "_FOREGROUND",
                            "FOREGROUND_APP",
                            "FOREGROUND",
                        ]
                        if not is_fg:
                            try:
                                adj_num = int(adj_value)
                                is_fg = adj_num <= 200
                            except Exception:
                                is_fg = False

                        if is_fg:
                            process_info[current_package]["is_foreground"] = True
                            logger.info(f"标记为前台: {current_package} (adj={adj_value})")

                        try:
                            if adj_value.startswith("_"):
                                adj_value = adj_value[1:]
                            process_info[current_package]["oom_adj"] = (
                                int(adj_value) if adj_value.isdigit() else 1000
                            )
                        except Exception:
                            pass

            logger.info(
                f"进程优先级检测完成: 找到 {len(process_info)} 个进程，前台进程: {[p for p, info in process_info.items() if info['is_foreground']]}"
            )
            return process_info

        except Exception as e:
            logger.error(f"获取进程优先级失败: {e}", exc_info=True)
            return {}

    def _get_process_priorities_fallback(self) -> dict:
        """
        备用方法：获取进程优先级信息
        使用 dumpsys activity top 作为备用方案

        Returns:
            dict: {package_name: {'is_foreground': bool, 'oom_adj': int}}
        """
        try:
            # 使用 _get_foreground_packages 方法获取前台应用
            foreground_packages = self._get_foreground_packages()

            logger.info(f"备用方法检测到前台应用: {foreground_packages}")

            # 构建返回结果
            process_info = {}
            for package_name in foreground_packages:
                process_info[package_name] = {
                    "is_foreground": True,
                    "oom_adj": 0,  # 前台应用默认 adj=0
                }

            return process_info

        except Exception as e:
            logger.warning(f"备用方法获取进程优先级失败: {e}")
            return {}

    def _get_foreground_packages(self) -> set:
        """
        获取当前前台应用的包名集合
        优先读取 dumpsys activity activities / dumpsys window windows 的 ResumedActivity / mCurrentFocus，
        再回退到 dumpsys activity top。

        Returns:
            set: 前台应用的包名集合
        """
        try:
            foreground_packages = set()

            # 1. 优先从 dumpsys activity activities 提取 ResumedActivity / topResumedActivity
            activities_out = self._adb.shell("dumpsys activity activities", self.device_id, timeout=10)
            if activities_out:
                for line in activities_out.split("\n"):
                    if any(
                        key in line
                        for key in ("ResumedActivity", "mResumedActivity", "topResumedActivity", "mFocusedActivity")
                    ):
                        match = re.search(r"(?:u\d+\s+)?([\w.]+)/", line.split(":", 1)[-1])
                        if match:
                            pkg = match.group(1)
                            if "." in pkg:
                                foreground_packages.add(pkg)

            # 2. 从 dumpsys window windows 提取 mCurrentFocus / mFocusedApp
            window_out = self._adb.shell("dumpsys window windows", self.device_id, timeout=10)
            if window_out:
                for line in window_out.split("\n"):
                    if "mCurrentFocus" in line or "mFocusedApp" in line:
                        match = re.search(r"u\d+\s+([\w.]+)/", line)
                        if match:
                            pkg = match.group(1)
                            if "." in pkg:
                                foreground_packages.add(pkg)

            if foreground_packages:
                return foreground_packages

            # 3. 兜底使用 dumpsys activity top
            output = self._adb.shell("dumpsys activity top", self.device_id, timeout=10)
            if not output:
                return set()

            # 解析输出，查找 ACTIVITY 和 mFocusedApp
            for line in output.split("\n"):
                if "ACTIVITY" in line and "/" in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        activity_info = parts[1]
                        package_name = activity_info.split("/")[0]
                        if "." in package_name:
                            foreground_packages.add(package_name)

                if "mFocusedApp" in line and "ActivityRecord" in line:
                    match = re.search(r"u0\s+([\w.]+)/", line)
                    if match:
                        package_name = match.group(1)
                        if "." in package_name:
                            foreground_packages.add(package_name)

            return foreground_packages

        except Exception as e:
            logger.warning(f"获取前台应用失败: {e}")
            return set()

    def get_app_info(self, package_name: str) -> Optional[AppInfo]:
        """
        获取Android应用详细信息

        Args:
            package_name: 包名

        Returns:
            AppInfo: 应用信息
        """
        return self._get_app_details(package_name)

    def get_app_memory_usage(self, package_name: str) -> float:
        """
        获取应用内存占用（MB）

        Args:
            package_name: 包名

        Returns:
            float: 内存占用（MB）
        """
        try:
            if not self._adb:
                return 0.0

            output = self._adb.shell(f"dumpsys meminfo {package_name}", self.device_id, timeout=10)
            if not output:
                return 0.0

            # 解析TOTAL内存
            for line in output.split("\n"):
                if "TOTAL:" in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            # 单位是KB，转换为MB
                            return float(parts[1]) / 1024.0
                        except ValueError:
                            pass

            return 0.0

        except Exception as e:
            logger.error(f"获取应用内存占用失败: {e}")
            return 0.0

    def get_app_cpu_usage(self, package_name: str) -> float:
        """
        获取应用CPU使用率

        Args:
            package_name: 包名

        Returns:
            float: CPU使用率（百分比）
        """
        try:
            if not self._adb:
                return 0.0

            # 获取应用PID
            pid = self._get_app_pid(package_name)
            if not pid:
                return 0.0

            # 使用top命令获取CPU使用率
            output = self._adb.shell("top -n 1", self.device_id, timeout=10)
            if not output:
                return 0.0

            # 使用 Python 解析而不是 grep
            for line in output.split("\n"):
                if str(pid) in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            return float(parts[2].replace("%", ""))
                        except (ValueError, IndexError):
                            pass

            return 0.0

        except Exception as e:
            logger.error(f"获取应用CPU使用率失败: {e}")
            return 0.0


class AppEnumeratorFactory:
    """
    应用枚举器工厂（支持 Android 和 iOS）
    """

    @staticmethod
    def create_enumerator(device_id: str, platform: Platform) -> Optional[BaseAppEnumerator]:
        """
        创建应用枚举器

        Args:
            device_id: 设备ID
            platform: 平台类型（Android 或 iOS）

        Returns:
            BaseAppEnumerator: 应用枚举器实例
        """
        # 比较枚举值而不是枚举本身
        if hasattr(platform, "value"):
            platform_value = platform.value
        else:
            platform_value = str(platform)

        if platform_value == "Android":
            return AndroidAppEnumerator(device_id)
        elif platform_value == "iOS":
            # 导入 iOS 枚举器
            from .ios_app_enumerator import IOSAppEnumerator

            return IOSAppEnumerator(device_id)
        else:
            logger.error(f"不支持的平台: {platform} (值: {platform_value})")
            return None
