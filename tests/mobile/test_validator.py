# -*- coding: utf-8 -*-
from __future__ import annotations

from insight_aitest.modules.mobile.backend.automation.validator import (
    lint_script_logs,
    validate_script_source,
    validate_staging_dir,
)


def test_validator_accepts_valid_appium_script():
    src = """
from appium.webdriver.common.appiumby import AppiumBy

def test_(driver, params, app_env):
    btn = driver.find_element(AppiumBy.ID, "com.demo:id/login")
    btn.click()
    assert app_env.get("app_package")
"""
    assert validate_script_source(src, require_test_entry=True) == ""


def test_validator_rejects_empty_and_syntax_error():
    assert validate_script_source("   ") != ""
    err = validate_script_source("def test_(driver):\n    if True\n        pass\n")
    assert "语法错误" in err


def test_validator_rejects_forbidden_modules_and_calls():
    err_mod = validate_script_source("import subprocess\ndef test_(driver):\n    pass\n")
    assert "subprocess" in err_mod

    err_eval = validate_script_source("def test_(driver):\n    eval('1+1')\n")
    assert "eval" in err_eval

    err_os = validate_script_source("import os\ndef test_(driver):\n    os.system('ls')\n")
    assert "os.system" in err_os


def test_validator_rejects_missing_test_entry_and_absolute_tap():
    err_entry = validate_script_source("def helper(driver):\n    pass\n", require_test_entry=True)
    assert "def test_" in err_entry

    err_tap = validate_script_source(
        "def test_(driver):\n    driver.tap([(500, 1200)])\n", require_test_entry=True
    )
    assert "绝对像素坐标" in err_tap


def test_validate_staging_dir_checks_case_and_pages(tmp_path):
    (tmp_path / "case.py").write_text(
        "def test_(driver):\n"
        "    print('[步骤] 启动被测应用')\n"
        "    print('[操作] 校验 driver 就绪')\n"
        "    print('[断言] driver 非空')\n"
        "    assert driver is not None\n",
        encoding="utf-8",
    )
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "login_page.py").write_text(
        "class LoginPage:\n    pass\n", encoding="utf-8"
    )
    assert validate_staging_dir(tmp_path) == ""

    (pages / "bad_page.py").write_text("import shutil\n", encoding="utf-8")
    err = validate_staging_dir(tmp_path)
    assert "bad_page.py" in err and "shutil" in err


def test_validator_enforces_log_nodes_on_staging(tmp_path):
    # 没有任何 print
    (tmp_path / "case.py").write_text(
        "def test_(driver):\n    assert driver is not None\n", encoding="utf-8"
    )
    err = validate_staging_dir(tmp_path)
    assert "执行日志缺失" in err

    # 少于 3 条 print
    src_few = (
        "def test_(driver):\n"
        "    print('[步骤] 进入首页')\n"
        "    print('[断言] 校验通过')\n"
        "    assert True\n"
    )
    assert "只有 2 条" in lint_script_logs(src_few)

    # 缺少 [步骤]
    src_no_step = (
        "def test_(driver):\n"
        "    print('[操作] 点击登录')\n"
        "    print('[输入] 账号')\n"
        "    print('[断言] 登录成功')\n"
    )
    assert "[步骤]" in lint_script_logs(src_no_step)

    # 缺少 [断言]/[校验]
    src_no_assert = (
        "def test_(driver):\n"
        "    print('[步骤] 进入登录页')\n"
        "    print('[输入] 账号')\n"
        "    print('[操作] 点击登录')\n"
    )
    assert "[断言]/[校验]" in lint_script_logs(src_no_assert)

    # 支持 f-string 与 [校验]
    src_ok = (
        "def test_(driver, app_env):\n"
        "    pkg = app_env.get('app_package')\n"
        "    print(f'[步骤] 启动应用 {pkg}')\n"
        "    print('[操作] 进入首页')\n"
        "    print(f'[校验] 当前包名 实际={pkg!r}')\n"
    )
    assert lint_script_logs(src_ok) == ""
