# -*- coding: utf-8 -*-
from __future__ import annotations

from insight_aitest.modules.mobile.backend.automation.validator import (
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
        "def test_(driver):\n    assert driver is not None\n", encoding="utf-8"
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
