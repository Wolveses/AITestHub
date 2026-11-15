# -*- coding: utf-8 -*-
"""App 自动化脚本 AST 静态安全校验与定位规范检查。

在试跑（dry_run）与提交固化（commit）前执行：
1. 校验 Python 语法（ast.parse）与可编译性；
2. 禁止危险系统调用（os.system / subprocess / eval / exec / shutil.rmtree 等）；
3. 必须包含至少一个接收 `driver` fixture 的 `def test_*(driver, ...)` 函数；
4. 禁止硬编码绝对像素点击（如 `driver.tap([(500, 1200)])`），要求使用控件定位或相对坐标。
"""

from __future__ import annotations

import ast
import py_compile
import tempfile
from pathlib import Path

_FORBIDDEN_MODULES = {"subprocess", "pty", "ctypes", "shutil", "socket"}
_FORBIDDEN_BUILTINS = {"eval", "exec", "compile", "__import__"}
_FORBIDDEN_ATTR_CALLS = {
    ("os", "system"),
    ("os", "popen"),
    ("os", "remove"),
    ("os", "unlink"),
    ("os", "rmdir"),
    ("os", "execv"),
    ("os", "execl"),
}


def validate_script_source(source: str, *, require_test_entry: bool = True) -> str:
    """校验脚本源码，返回空串表示通过，否则返回具体原因。"""
    if not (source or "").strip():
        return "脚本内容不能为空"

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return f"Python 语法错误 (line {e.lineno}): {e.msg}"

    has_test_fn = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _FORBIDDEN_MODULES:
                    return f"安全限制：禁止导入模块 `{top}`"
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in _FORBIDDEN_MODULES:
                return f"安全限制：禁止从模块 `{top}` 导入"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_BUILTINS:
                return f"安全限制：禁止调用 `{node.func.id}()`"
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                pair = (node.func.value.id, node.func.attr)
                if pair in _FORBIDDEN_ATTR_CALLS:
                    return f"安全限制：禁止调用 `{pair[0]}.{pair[1]}()`"
            # 禁用 driver.tap([(x, y)]) 绝对像素点击
            if isinstance(node.func, ast.Attribute) and node.func.attr == "tap":
                if _has_numeric_coords(node):
                    return (
                        "定位规范限制：禁止使用绝对像素坐标 `tap([(x, y)])`，"
                        "请改用 `AppiumBy` 控件定位或按屏幕宽高比例计算相对坐标"
                    )
        elif isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            arg_names = [a.arg for a in node.args.args]
            if "driver" in arg_names:
                has_test_fn = True

    if require_test_entry and not has_test_fn:
        return "脚本必须至少包含一个接收 `driver` fixture 的 `def test_*(driver, ...)` 用例函数"

    # 进一步编译校验
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=True) as tmp:
            tmp.write(source)
            tmp.flush()
            py_compile.compile(tmp.name, doraise=True)
    except py_compile.PyCompileError as e:
        return f"脚本编译校验失败: {e}"

    return ""


def _has_numeric_coords(call_node: ast.Call) -> bool:
    """检测 tap(...) 调用中是否直接传入数字坐标字面量。"""
    for arg in list(call_node.args) + [kw.value for kw in call_node.keywords]:
        if isinstance(arg, (ast.List, ast.Tuple)):
            for elt in ast.walk(arg):
                if isinstance(elt, ast.Tuple) and len(elt.elts) == 2:
                    if all(isinstance(c, ast.Constant) and isinstance(c.value, (int, float)) for c in elt.elts):
                        return True
    return False


def validate_staging_dir(staging: Path) -> str:
    """校验暂存区主脚本及所有 pages/*.py。"""
    case_file = staging / "case.py"
    if not case_file.exists():
        return "暂存区缺少 case.py"
    err = validate_script_source(case_file.read_text(encoding="utf-8"), require_test_entry=True)
    if err:
        return f"case.py 校验失败: {err}"

    pages = staging / "pages"
    if pages.exists():
        for py in sorted(pages.glob("*.py")):
            if py.name == "__init__.py":
                continue
            p_err = validate_script_source(
                py.read_text(encoding="utf-8"), require_test_entry=False
            )
            if p_err:
                return f"pages/{py.name} 校验失败: {p_err}"
    return ""
