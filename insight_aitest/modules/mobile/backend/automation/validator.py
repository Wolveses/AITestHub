# -*- coding: utf-8 -*-
"""App 自动化脚本 AST 静态安全校验与定位/日志规范检查。

在试跑（dry_run）与提交固化（commit）前执行：
1. 校验 Python 语法（ast.parse）与可编译性；
2. 禁止危险系统调用（os.system / subprocess / eval / exec / shutil.rmtree 等）；
3. 必须包含至少一个接收 `driver` fixture 的 `def test_*(driver, ...)` 函数；
4. 禁止硬编码绝对像素点击（如 `driver.tap([(500, 1200)])`），要求使用控件定位或相对坐标；
5. 日志规范（MCP 生成校验）：每个测试函数至少 3 条 `print(...)` 日志，且包含 `[步骤]` 与 `[断言]`/`[校验]` 节点前缀。
"""

from __future__ import annotations

import ast
import py_compile
import tempfile
from pathlib import Path

MIN_LOGS_PER_TEST = 3
LOG_PREFIXES = ("[步骤]", "[操作]", "[输入]", "[选择]", "[勾选]", "[断言]", "[校验]", "[数据]", "[结果]")

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


def _literal_text(node: ast.AST | None) -> str:
    """取出 print 首个参数的静态文本（含 f-string 的固定片段）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return ""


def _lint_logs_tree(tree: ast.AST) -> str:
    """校验执行日志规范（对齐 UI 自动化）：每个 test_* 至少 3 条 print，且含 [步骤] 与 [断言]/[校验]。"""
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not fn.name.startswith("test_"):
            continue
        prints: list[tuple[int, str]] = []
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                prints.append((node.lineno, _literal_text(node.args[0] if node.args else None)))
        if not prints:
            return (
                f"执行日志缺失：{fn.name} 没有任何 print 执行日志；"
                f"每个测试函数至少 {MIN_LOGS_PER_TEST} 条带 [步骤]/[操作]/[断言] 前缀的 print"
            )
        if len(prints) < MIN_LOGS_PER_TEST:
            return (
                f"执行日志过少：{fn.name} 只有 {len(prints)} 条 print 日志，"
                f"至少需要 {MIN_LOGS_PER_TEST} 条（建议含 [步骤]、[操作]/[输入]、[断言]/[结果]）"
            )
        text = "".join(chunk for _, chunk in prints)
        if "[步骤]" not in text:
            return f"日志格式不规范：{fn.name} 缺少 [步骤] 日志（例：print('[步骤] 启动应用并进入目标页')）"
        if "[断言]" not in text and "[校验]" not in text:
            return (
                f"日志格式不规范：{fn.name} 缺少 [断言]/[校验] 日志"
                "（断言前打印实际值与预期值，例：print(f'[断言] 实际={actual!r} 预期={expected!r}')）"
            )
    return ""


def lint_script_logs(source: str) -> str:
    """单独校验脚本源码是否满足执行日志规范，返回空串表示通过。"""
    if not (source or "").strip():
        return "脚本内容不能为空"
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return f"Python 语法错误 (line {e.lineno}): {e.msg}"
    return _lint_logs_tree(tree)


def validate_script_source(
    source: str, *, require_test_entry: bool = True, require_logs: bool = False
) -> str:
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

    if require_logs:
        log_err = _lint_logs_tree(tree)
        if log_err:
            return log_err

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


def validate_staging_dir(staging: Path, *, require_logs: bool = True) -> str:
    """校验暂存区主脚本及所有 pages/*.py。"""
    case_file = staging / "case.py"
    if not case_file.exists():
        return "暂存区缺少 case.py"
    err = validate_script_source(
        case_file.read_text(encoding="utf-8"),
        require_test_entry=True,
        require_logs=require_logs,
    )
    if err:
        return f"case.py 校验失败: {err}"

    pages = staging / "pages"
    if pages.exists():
        for py in sorted(pages.glob("*.py")):
            if py.name == "__init__.py":
                continue
            p_err = validate_script_source(
                py.read_text(encoding="utf-8"), require_test_entry=False, require_logs=False
            )
            if p_err:
                return f"pages/{py.name} 校验失败: {p_err}"
    return ""
