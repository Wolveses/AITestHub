# -*- coding: utf-8 -*-
"""AI 自动化脚本（Playwright + pytest）子包。

与旧的 Midscene 视觉驱动链路（engine/executor）并存，互不影响：
- 旧链路：ui_runs.runner='midscene'，用例来自 testcase 模块；
- 新链路：ui_cases 资产 + ui_runs.runner='script'，用例从知识库用例文档快照导入。

存储根目录默认 ~/.insight_eye（可配 ui_workspace_dir），数据库复用 ui.db。
"""
