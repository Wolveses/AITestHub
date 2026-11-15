# -*- coding: utf-8 -*-
"""
Android 内存采集器
使用 ADB 实现 Android 应用的内存使用数据采集

改进：
- 集成设备配置系统（DeviceProfile）
- 根据设备配置选择内存单位（MB/KB）
"""

import re
from typing import Optional, Dict
from logzero import logger
from insight_aitest.platform.services.collectors.adb import adb
from insight_aitest.platform.services.device_common import DEVICE_GLOBAL_TARGET


class MemoryCollector:
    """
    Android 内存使用情况采集器 - 集成设备配置系统

    使用 ADB shell dumpsys meminfo 命令获取应用的内存使用量
    """

    def __init__(self, device_id: str, device_profile=None):
        """
        初始化内存采集器

        Args:
            device_id: Android 设备 ID
            device_profile: 设备配置档案（可选）
        """
        self.device_id = device_id
        self.device_profile = device_profile
        self.strategy = device_profile.get_strategy() if device_profile else None
        self._total_memory_mb: Optional[float] = None

        if self.strategy:
            logger.debug(
                f"[内存采集器] 使用策略: {self.strategy.memory_primary_method}, "
                f"单位: {self.strategy.memory_unit}"
            )

    def _get_device_total_memory_mb(self) -> Optional[float]:
        """读取并缓存设备物理总内存（MB）"""
        if self._total_memory_mb is not None:
            return self._total_memory_mb
        try:
            output = adb.shell("cat /proc/meminfo", self.device_id)
            if output:
                match = re.search(r"MemTotal:\s*(\d+)\s*kB", output, re.IGNORECASE)
                if match:
                    self._total_memory_mb = round(float(match.group(1)) / 1024.0, 2)
                    return self._total_memory_mb
        except Exception as e:
            logger.debug(f"读取 /proc/meminfo 失败: {e}")
        return None

    def _enrich_with_device_total(self, data: Dict[str, float]) -> Dict[str, float]:
        """附加设备总内存与内存占用百分比"""
        total_mb = self._get_device_total_memory_mb()
        if total_mb and total_mb > 0:
            used_mb = float(data.get("totalPass", 0) or 0)
            data["total_mb"] = total_mb
            data["percentage"] = round((used_mb / total_mb) * 100.0, 2)
        return data

    def _parse_memory_from_dumpsys(self, package_name: str) -> Optional[Dict[str, float]]:
        """
        使用 dumpsys meminfo 解析内存使用情况

        Args:
            package_name: 应用包名

        Returns:
            dict: {
                'totalPass': float,     # 总内存 (MB)
                'nativePass': float,    # Native 内存 (MB)
                'dalvikPass': float,    # Dalvik 内存 (MB)
            } 或 None
        """
        try:
            result = adb.shell(f"dumpsys meminfo {package_name}", self.device_id)

            if not result:
                return None

            lines = result.strip().split("\n")

            # 初始化内存变量
            total_pass = 0.0  # Total RSS (Resident Set Size)
            native_heap = 0.0  # Native Heap
            dalvik_heap = 0.0  # Dalvik Heap
            java_heap = 0.0  # Java Heap
            code = 0.0  # Code
            stack = 0.0  # Stack
            graphics = 0.0  # Graphics
            private_other = 0.0  # Private Other
            system = 0.0  # System

            for line in lines:
                # Android 8.0+ 格式解析
                # 格式: "Total RSS: 123456 kB" 或 "Total PSS: 123456 kB"
                if "Total RSS" in line or "Total PSS" in line:
                    match = re.search(r"Total\s+(?:RSS|PSS):\s+(\d+)\s+kB", line)
                    if match:
                        total_pass = float(match.group(1)) / 1024  # 转换为 MB

                # Native Heap 解析
                elif "Native Heap" in line:
                    match = re.search(r"Native Heap:\s+(\d+)\s+kB", line)
                    if match:
                        native_heap = float(match.group(1)) / 1024

                # Dalvik/Java Heap 解析
                elif "Dalvik Heap" in line:
                    match = re.search(r"Dalvik Heap:\s+(\d+)\s+kB", line)
                    if match:
                        dalvik_heap = float(match.group(1)) / 1024
                elif "Java Heap:" in line:
                    match = re.search(r"Java Heap:\s+(\d+)\s+kB", line)
                    if match:
                        java_heap = float(match.group(1)) / 1024

                # Code 解析
                elif "Code" in line and "Heap" not in line:
                    match = re.search(r"Code:\s+(\d+)\s+kB", line)
                    if match:
                        code = float(match.group(1)) / 1024

                # Stack 解析
                elif "Stack" in line:
                    match = re.search(r"Stack:\s+(\d+)\s+kB", line)
                    if match:
                        stack = float(match.group(1)) / 1024

                # Graphics 解析
                elif "Graphics" in line:
                    match = re.search(r"Graphics:\s+(\d+)\s+kB", line)
                    if match:
                        graphics = float(match.group(1)) / 1024

                # Private Other 解析
                elif "Private Other" in line:
                    match = re.search(r"Private Other:\s+(\d+)\s+kB", line)
                    if match:
                        private_other = float(match.group(1)) / 1024

                # System 解析
                elif "System" in line and "System UI" not in line:
                    match = re.search(r"System:\s+(\d+)\s+kB", line)
                    if match:
                        system = float(match.group(1)) / 1024

            # 如果解析到 Total RSS，使用它
            if total_pass > 0:
                return {
                    "totalPass": round(total_pass, 2),
                    "nativePass": round(native_heap, 2),
                    "dalvikPass": round(dalvik_heap + java_heap, 2),
                }

            # 如果没有 Total RSS，使用各部分总和
            total = (
                native_heap
                + dalvik_heap
                + java_heap
                + code
                + stack
                + graphics
                + private_other
                + system
            )
            if total > 0:
                return {
                    "totalPass": round(total, 2),
                    "nativePass": round(native_heap, 2),
                    "dalvikPass": round(dalvik_heap + java_heap, 2),
                }

            return None

        except Exception as e:
            logger.error(f"使用 dumpsys 获取内存失败: {e}")
            return None

    def _parse_memory_simple(self, package_name: str) -> Optional[Dict[str, float]]:
        """
        简化内存解析方法（兼容旧版本 Android）

        Args:
            package_name: 应用包名

        Returns:
            dict: 内存数据或 None
        """
        try:
            result = adb.shell(f"dumpsys meminfo {package_name}", self.device_id)

            if not result:
                return None

            lines = result.strip().split("\n")

            for line in lines:
                # 查找类似 "TOTAL: 123456 (total)" 或 "TOTAL   123456" 的行
                if "TOTAL" in line:
                    match = re.search(r"TOTAL[:\s]+(\d+)", line)
                    if match:
                        total_kb = float(match.group(1))
                        total_mb = total_kb / 1024

                        return {
                            "totalPass": round(total_mb, 2),
                            "nativePass": round(total_mb * 0.3, 2),  # 估算 Native 内存
                            "dalvikPass": round(total_mb * 0.4, 2),  # 估算 Dalvik 内存
                        }

            return None

        except Exception as e:
            logger.error(f"简化内存解析失败: {e}")
            return None

    def collect_device(self) -> Dict[str, float]:
        """采集整台设备的全局物理内存使用量（基于 /proc/meminfo）"""
        try:
            output = adb.shell("cat /proc/meminfo", self.device_id)
            if output:
                values: Dict[str, float] = {}
                for line in output.splitlines():
                    match = re.match(r"^([A-Za-z0-9_()]+):\s+(\d+)\s*kB", line.strip())
                    if match:
                        values[match.group(1)] = float(match.group(2))

                total_kb = values.get("MemTotal", 0.0)
                if total_kb > 0:
                    if "MemAvailable" in values:
                        avail_kb = values["MemAvailable"]
                    else:
                        avail_kb = (
                            values.get("MemFree", 0.0)
                            + values.get("Buffers", 0.0)
                            + values.get("Cached", 0.0)
                            + values.get("SReclaimable", 0.0)
                        )
                    used_kb = max(0.0, total_kb - avail_kb)
                    total_mb = round(total_kb / 1024.0, 2)
                    used_mb = round(used_kb / 1024.0, 2)
                    self._total_memory_mb = total_mb
                    return {
                        "totalPass": used_mb,
                        "nativePass": 0.0,
                        "dalvikPass": 0.0,
                        "total_mb": total_mb,
                        "percentage": round((used_mb / total_mb) * 100.0, 2),
                    }
        except Exception as e:
            logger.error(f"Android 整机内存采集失败: {e}")

        return self._enrich_with_device_total(
            {"totalPass": 0.0, "nativePass": 0.0, "dalvikPass": 0.0}
        )

    def collect(self, package_name: str) -> Optional[Dict[str, float]]:
        """
        采集内存使用情况

        Args:
            package_name: 应用包名 (如 com.example.app)，或 DEVICE_GLOBAL_TARGET 表示整机全局

        Returns:
            dict: {
                'totalPass': float,     # 总内存 (MB)
                'nativePass': float,    # Native 内存 (MB)
                'dalvikPass': float,    # Dalvik 内存 (MB)
            } 或 None

        注意：
            - totalPass: 应用总内存使用量（基于 RSS/PSS）
            - nativePass: Native 堆内存（C/C++ 代码使用）
            - dalvikPass: Dalvik/Java 堆内存（Java/Kotlin 代码使用）
            - 返回单位为 MB
        """
        if package_name == DEVICE_GLOBAL_TARGET:
            return self.collect_device()

        try:
            # 方法1: 使用完整 dumpsys meminfo 解析
            result = self._parse_memory_from_dumpsys(package_name)
            if result:
                return self._enrich_with_device_total(result)

            # 方法2: 使用简化解析
            result = self._parse_memory_simple(package_name)
            if result:
                return self._enrich_with_device_total(result)

            # 如果都失败，返回默认值
            logger.debug(f"无法获取 {package_name} 的内存使用情况")
            return self._enrich_with_device_total(
                {"totalPass": 0, "nativePass": 0, "dalvikPass": 0}
            )

        except Exception as e:
            logger.error(f"Android 内存采集失败: {e}")
            # 返回默认值而非 None，避免后续处理失败
            return self._enrich_with_device_total(
                {"totalPass": 0, "nativePass": 0, "dalvikPass": 0}
            )
