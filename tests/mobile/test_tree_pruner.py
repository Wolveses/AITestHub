# -*- coding: utf-8 -*-
from __future__ import annotations

from insight_aitest.modules.mobile.backend.automation.tree_pruner import prune_android_xml

SAMPLE_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <android.widget.FrameLayout index="0" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]" displayed="true">
    <android.widget.LinearLayout index="0" class="android.widget.LinearLayout" bounds="[0,0][0,0]" clickable="true">
      <android.widget.TextView index="0" class="android.widget.TextView" text="ZeroSizeHidden" bounds="[0,0][0,0]" />
    </android.widget.LinearLayout>
    <android.widget.Button index="1" class="android.widget.Button" resource-id="com.demo:id/btn_login"
        content-desc="登录按钮" text="登录" clickable="true" enabled="true" bounds="[100,500][980,620]" displayed="true" />
    <android.widget.EditText index="2" class="android.widget.EditText" resource-id="com.demo:id/et_pwd"
        hint="请输入密码" password="true" clickable="true" focusable="true" enabled="true" bounds="[100,300][980,420]" displayed="true" />
    <android.widget.View index="3" class="android.widget.View" bounds="[0,0][1080,2400]" clickable="false" />
    <android.widget.TextView index="4" class="android.widget.TextView" text="欢迎使用测试平台"
        bounds="[100,150][980,220]" displayed="true" />
    <android.widget.TextView index="5" class="android.widget.TextView" text="InvisibleNode"
        bounds="[100,700][400,760]" displayed="false" />
  </android.widget.FrameLayout>
</hierarchy>
"""


def test_prune_android_xml_filters_and_assigns_refs():
    snap = prune_android_xml(SAMPLE_XML, activity=".LoginActivity", screen_size=(1080, 2400))

    assert ".LoginActivity" in snap.text
    assert "1080x2400" in snap.text
    assert snap.kept_nodes == 3
    assert "ZeroSizeHidden" not in snap.text
    assert "InvisibleNode" not in snap.text

    # e1 -> Button with content-desc -> accessibility_id recommended
    e1 = snap.refs["e1"]
    strat, val, snippet = e1.recommended_locator()
    assert strat == "accessibility_id"
    assert val == "登录按钮"
    assert "AppiumBy.ACCESSIBILITY_ID" in snippet

    # e2 -> EditText with resource-id -> id recommended
    e2 = snap.refs["e2"]
    strat2, val2, snippet2 = e2.recommended_locator()
    assert strat2 == "id"
    assert val2 == "com.demo:id/et_pwd"
    assert "AppiumBy.ID" in snippet2
    assert e2.password is True


def test_prune_android_xml_compact_mode_omits_bounds_and_id_only_containers():
    xml_with_container = SAMPLE_XML.replace(
        '<android.widget.View index="3"',
        '<android.widget.View index="3" resource-id="com.demo:id/divider"',
    )
    normal = prune_android_xml(xml_with_container, compact=False)
    compact = prune_android_xml(xml_with_container, compact=True)
    assert normal.kept_nodes == 4
    assert compact.kept_nodes == 3
    assert "com.demo:id/divider" in normal.text
    assert "com.demo:id/divider" not in compact.text
    assert "bounds=" in normal.text
    assert "bounds=" not in compact.text
    assert "hint=" not in compact.text


def test_prune_android_xml_preserves_whitespace_in_content_desc():
    xml = (
        '<hierarchy rotation="0">'
        '<android.widget.Button index="0" class="android.widget.Button" '
        'content-desc=" 连接设备" clickable="true" bounds="[10,10][200,80]" />'
        "</hierarchy>"
    )
    snap = prune_android_xml(xml)
    assert snap.refs["e1"].content_desc == " 连接设备"
    assert snap.refs["e1"].recommended_locator()[1] == " 连接设备"
