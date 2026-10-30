# -*- coding: utf-8 -*-
"""UI 自动化链路的 golden 回归（不调用任何大模型）。

部署前跑一次，验证「仓库机制升级后旧资产仍可运行」：
1. 环境契约 env 函数齐全、签名向后兼容（脚本只允许依赖它）；
2. 项目资产目录（common/ + pages/）可被生成器发现（pages_catalog）；
3. 资产落位规则生效（pages 禁止覆盖、common 允许覆盖并自动备份到 common/history/）；
4. （默认执行）用力例的真实固化脚本跑一遍执行链路。

用法：
    python scripts/verify_ui_automation.py --project 1
    python scripts/verify_ui_automation.py --project 1 --case 1
    python scripts/verify_ui_automation.py --project 1 --skip-run   # 只做静态检查
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from insight_aitest.modules.ui.backend.automation import env, paths  # noqa: E402
from insight_aitest.modules.ui.backend.automation.generator import (  # noqa: E402
    _check_sandbox,
    adopt_pages,
    discard_pages,
    pages_catalog,
    stage_pages,
)
from insight_aitest.modules.ui.backend.automation.runner import run_script  # noqa: E402

# 仓库对脚本暴露的全部契约（脚本只能依赖这三个函数，页面/字段语义一律在用户目录资产）
REQUIRED_CONTRACT = ("base_url", "data_path", "artifact_path")

API_SNAPSHOT = Path(__file__).resolve().parent / "contract_api.json"

CHECKS: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok))
    print(("[通过] " if ok else "[失败] ") + name + (f"  {detail}" if detail else ""))


def env_api() -> dict[str, str]:
    """环境契约对外签名快照（用于阻止发布时无声改动接口）。"""
    import inspect

    api: dict[str, str] = {}
    for name in dir(env):
        if name.startswith("_"):
            continue
        obj = getattr(env, name)
        if inspect.isfunction(obj) and obj.__module__ == env.__name__:
            api[name] = str(inspect.signature(obj))
    return dict(sorted(api.items()))


def check_api_snapshot(update: bool) -> None:
    import json

    current = env_api()
    if update:
        API_SNAPSHOT.write_text(
            json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        check("环境契约签名快照已更新", True, str(API_SNAPSHOT))
        return
    if not API_SNAPSHOT.exists():
        check("环境契约签名快照存在", False, "缺少 scripts/contract_api.json，请加 --update-api")
        return
    baseline = json.loads(API_SNAPSHOT.read_text(encoding="utf-8"))
    removed = [n for n in baseline if n not in current]
    changed = [n for n in baseline if n in current and baseline[n] != current[n]]
    check(
        "环境契约签名向后兼容",
        not removed and not changed,
        f"删除={removed} 变更签名={changed}" if (removed or changed) else f"{len(current)} 个函数",
    )
    added = [n for n in current if n not in baseline]
    if added:
        print(f"  提示：新增函数 {added}，发版前请执行 --update-api 更新快照")


def check_static(project_id: int) -> None:
    missing = [n for n in REQUIRED_CONTRACT if not callable(getattr(env, n, None))]
    check("环境契约函数齐全", not missing, "缺少：" + ", ".join(missing) if missing else "")

    catalog = pages_catalog(project_id)
    has_files = any(
        p.name != "__init__.py"
        for root in (paths.common_dir(project_id), paths.pages_dir(project_id))
        for p in root.glob("*.py")
    )
    check(
        "项目资产可被生成器发现",
        bool(catalog) or not has_files,
        "common/ 与 pages/ 暂无可复用资产时视为通过"
        if not has_files
        else f"{len(catalog.splitlines())} 行签名",
    )

    temp_project = 10_000_000  # 临时项目，检查完即删
    pages_root = paths.pages_dir(temp_project)
    common_root = paths.common_dir(temp_project)
    try:
        (pages_root / "users_page.py").write_text("x = 1\n", encoding="utf-8")
        err, _ = stage_pages(
            temp_project, 9001, [{"path": "pages/users_page.py", "content": "x = 2\n"}]
        )
        check("页面对象禁止覆盖", bool(err), err)

        (common_root / "ui.py").write_text("x = 1\n", encoding="utf-8")
        err, staged = stage_pages(
            temp_project, 9002, [{"path": "common/ui.py", "content": "x = 2\n"}]
        )
        check("common 可暂存覆盖", not err, err)
        check(
            "未通过首跑不落正式资产",
            (common_root / "ui.py").read_text(encoding="utf-8") == "x = 1\n",
            "暂存内容不应出现在 common/",
        )
        adopt_pages(temp_project, staged)
        check(
            "首跑通过后并入正式资产",
            (common_root / "ui.py").read_text(encoding="utf-8") == "x = 2\n",
            str(common_root / "ui.py"),
        )
        backups = list((common_root / "history").glob("*.py"))
        check("覆盖旧版自动备份", bool(backups), f"{len(backups)} 个备份")
        discard_pages(staged)

        bad = stage_pages(temp_project, 9003, [{"path": "../evil.py", "content": "x = 1\n"}])
        check("目录穿越被拒绝", bool(bad[0]), bad[0])

        unsafe, _ = stage_pages(
            temp_project, 9004, [{"path": "pages/bad_page.py", "content": "import os\n"}]
        )
        check("资产 import 白名单生效", bool(unsafe), unsafe)
        discard_pages(paths.staging_root(temp_project, 9004))

        sandbox = _check_sandbox(
            "import os\n\ndef test_x(page):\n    page.wait_for_timeout(500)\n", kind="脚本"
        )
        sleep_blocked = _check_sandbox(
            "def test_x(page):\n    page.wait_for_timeout(500)\n", kind="脚本"
        )
        check("脚本禁止导入 os", bool(sandbox), sandbox)
        check("脚本禁止固定睡眠（AST）", bool(sleep_blocked), sleep_blocked)
    finally:
        shutil.rmtree(paths.project_scripts_dir(temp_project), ignore_errors=True)
        shutil.rmtree(paths.staging_root(temp_project, 9001).parents[0], ignore_errors=True)


def check_run(project_id: int, case_id: int | None) -> None:
    from insight_aitest.modules.ui.backend.automation.deps import get_automation_db

    db = get_automation_db()
    case = db.get_case(case_id) if case_id else None
    if case is None:
        items, _ = db.list_cases(project_id, page_size=200)
        candidates = [c for c in items if (c.script_rel_path or "").strip()]
        case = candidates[0] if candidates else None
    if case is None:
        check("存在可回归的固化脚本", False, "该项目下没有已生成脚本的用例")
        return

    env_row = db.default_env(project_id)
    script = paths.case_script(project_id, int(case.id))
    check("固化脚本文件存在", script.exists(), str(script))
    if not script.exists():
        return

    result = run_script(case, env_row, script_path=script)
    ok = result.get("status") == "passed"
    check(
        f"用例 {case.id} 执行通过",
        ok,
        f"status={result.get('status')} {result.get('error_message') or ''} "
        f"{result.get('duration_ms', 0)}ms {result.get('artifacts_rel_path') or ''}".strip(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="UI 自动化 golden 回归（不消耗模型 token）")
    parser.add_argument("--project", type=int, default=1, help="项目 id，默认 1")
    parser.add_argument("--case", type=int, default=None, help="指定用例 id，默认取首个已生成脚本的用例")
    parser.add_argument("--skip-run", action="store_true", help="只做静态检查，不跑真实脚本")
    parser.add_argument(
        "--update-api", action="store_true", help="更新环境契约签名快照（发版前契约变更时使用）"
    )
    args = parser.parse_args()

    check_api_snapshot(args.update_api)
    check_static(args.project)
    if not args.skip_run:
        check_run(args.project, args.case)

    failed = [name for name, ok in CHECKS if not ok]
    print(f"\n结果：{len(CHECKS) - len(failed)}/{len(CHECKS)} 通过")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
