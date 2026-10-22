# -*- coding: utf-8 -*-
"""Word 旧版文档 Loader（.doc）。

.doc 是 Word 97-2003 的 OLE2 复合二进制格式，python-docx 无法直接读取。
方案：调用 LibreOffice headless 转换为 .docx，再复用 DocxLoader 解析，
保证中文、表格、样式的解析质量与 .docx 完全一致，且不引入新的 Python 依赖。

运行环境需安装 LibreOffice（Windows/macOS/Linux 均可）；未安装时该格式
报错并提示安装。可用环境变量 INSIGHT_EYE_SOFFICE_PATH 显式指定可执行文件路径。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from insight_aitest.platform.services.kb.loader import register_loader
from insight_aitest.platform.services.kb.loader.base import DocumentLoadError, DocumentLoader
from insight_aitest.platform.services.kb.models import ParsedDocument

# 与 DocxLoader 共用体积上限：转换过程需整份载入内存
_MAX_SIZE = 20 * 1024 * 1024
_CONVERT_TIMEOUT = 120

_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04"

_soffice_cache: str | None | bool = None  # False 表示已探测过且未找到


def _prefer_console_launcher(exe: str) -> str:
    """Windows 上 soffice.exe 属 GUI 子系统，调用后立即返回且不产出文件；
    同目录的 soffice.com 是控制台入口，会阻塞到转换完成。其余平台原样返回。"""
    p = Path(exe)
    if p.suffix.lower() == ".exe":
        console = p.with_suffix(".com")
        if console.exists():
            return str(console)
    return exe


def _find_soffice() -> str | None:
    """定位 soffice 可执行文件（结果缓存）；未安装返回 None。"""
    global _soffice_cache
    if _soffice_cache is not None:
        return _soffice_cache or None

    env_path = os.environ.get("INSIGHT_EYE_SOFFICE_PATH")
    if env_path and Path(env_path).exists():
        _soffice_cache = _prefer_console_launcher(env_path)
        return _soffice_cache

    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            _soffice_cache = _prefer_console_launcher(found)
            return _soffice_cache

    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            _soffice_cache = _prefer_console_launcher(candidate)
            return _soffice_cache

    _soffice_cache = False
    return None


@register_loader(".doc")
class DocLoader(DocumentLoader):
    """Word .doc（OLE2）文档 Loader：LibreOffice 转 docx 后复用 DocxLoader。"""

    def load(self, path: Path) -> ParsedDocument:
        size = path.stat().st_size
        if size > _MAX_SIZE:
            raise DocumentLoadError(
                f"Word 文件过大 ({size // (1024 * 1024)}MB > 20MB)，解析会耗尽内存，请适当精简后导入。"
            )

        # 读取前 8 字节判魔数：部分文件实为 .docx 仅后缀写错（飞书导出常见），直接解析免转换
        with path.open("rb") as fp:
            head = fp.read(8)

        if head.startswith(_ZIP_MAGIC):
            parsed = self._load_docx(path)
        else:
            parsed = self._load_via_libreoffice(path)

        # 还原原始文件名与格式标记，避免下游看到临时 docx 名
        parsed.filename = path.name
        parsed.meta.update({"format": "doc"})
        return parsed

    @staticmethod
    def _load_docx(path: Path) -> ParsedDocument:
        from insight_aitest.platform.services.kb.loader.docx import DocxLoader

        return DocxLoader().load(path)

    def _load_via_libreoffice(self, path: Path) -> ParsedDocument:
        soffice = _find_soffice()
        if not soffice:
            raise DocumentLoadError(
                "未检测到 LibreOffice，无法解析 .doc（旧版 Word）文件。"
                "请在服务器安装 LibreOffice 后重新解析。"
            )

        workdir = Path(tempfile.mkdtemp(prefix="insight_doc_"))
        try:
            # 独立 UserInstallation profile：soffice 单实例共享默认 profile，
            # 并发调用会互相阻塞并出现「返回 0 但无产物」，必须隔离
            profile = workdir / "profile"
            profile.mkdir()
            outdir = workdir / "out"
            outdir.mkdir()

            cmd = [
                soffice,
                "--headless",
                "--norestore",
                "--nolockcheck",
                "--nodefault",
                "--invisible",
                f"-env:UserInstallation={profile.as_uri()}",
                "--convert-to",
                "docx:MS Word 2007 XML",
                "--outdir",
                str(outdir),
                str(path),
            ]
            run_kwargs: dict = {
                "capture_output": True,
                "text": True,
                "errors": "ignore",
                "timeout": _CONVERT_TIMEOUT,
            }
            if sys.platform == "win32":
                run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            try:
                proc = subprocess.run(cmd, **run_kwargs)
            except subprocess.TimeoutExpired:
                raise DocumentLoadError(
                    f".doc 转换超时（>{_CONVERT_TIMEOUT}s），请检查文件是否损坏或过大。"
                )

            converted = outdir / f"{path.stem}.docx"
            if proc.returncode != 0 or not converted.exists() or converted.stat().st_size == 0:
                detail = (proc.stderr or proc.stdout or "").strip()[-300:]
                raise DocumentLoadError(
                    f"LibreOffice 转换 .doc 失败: {detail or '未生成 docx 产物'}"
                )

            return self._load_docx(converted)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
