# -*- coding: utf-8 -*-
"""UI 自动化链路的 golden 回归（不调用任何大模型）。

部署前跑一次，验证「仓库机制升级后旧资产仍可运行」：
1. 脚手架插件与公共函数库可导入、签名齐全；
2. 项目页面对象目录可被生成器发现（pages_catalog）；
3. pages 落位规则生效（业务页面对象禁止覆盖、_utils.py 允许覆盖并自动备份）；
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

from insight_aitest.modules.ui.backend.automation import helpers, paths  # noqa: E402
from insight_aitest.modules.ui.backend.automation.generator import (  # noqa: E402
    UTILS_FILE,
    pages_catalog,
    write_pages,
)
from insight_aitest.modules.ui.backend.automation.runner import run_script  # noqa: E402

REQUIRED_HELPERS = (
    "base_url",
    "open_route",
    "dialog_of",
    "fill_text_fields",
    "confirm_dialog",
    "cancel_dialog",
    "row_by_text",
    "assert_row_contains",
    "unique_name",
)

CHECKS: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok))
    print(("[通过] " if ok else "[失败] ") + name + (f"  {detail}" if detail else ""))


def check_static(project_id: int) -> None:
    missing = [n for n in REQUIRED_HELPERS if not callable(getattr(helpers, n, None))]
    check("公共函数库签名齐全", not missing, "缺少：" + ", ".join(missing) if missing else "")

    root = paths.pages_dir(project_id)
    catalog = pages_catalog(project_id)
    check("页面对象目录已就绪", root.exists(), str(root))
    check("页面对象可被生成器发现", bool(catalog) or not any(
        p.name != "__init__.py" for p in root.glob("*.py")
    ), "空目录视为通过")

    temp_root = paths.pages_dir(10_000_000)  # 临时项目，检查完即删
    try:
        (temp_root / "users_page.py").write_text("x = 1\n", encoding="utf-8")
        refused = write_pages(
            10_000_000, [{"path": "pages/users_page.py", "content": "x = 2\n"}]
        )
        check("业务页面对象禁止覆盖", bool(refused), refused)
        (temp_root / UTILS_FILE).write_text("x = 1\n", encoding="utf-8")
        allowed = write_pages(10_000_000, [{"path": f"pages/{UTILS_FILE}", "content": "x = 2\n"}])
        backups = list((temp_root / "history").glob("*.py"))
        check("_utils.py 允许覆盖并备份", not allowed and bool(backups))
        bad = write_pages(10_000_000, [{"path": "../evil.py", "content": "x = 1\n"}])
        check("目录穿越被拒绝", bool(bad), bad)
    finally:
        shutil.rmtree(temp_root.parent, ignore_errors=True)


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

    env = db.default_env(project_id)
    script = paths.case_script(project_id, int(case.id))
    check("固化脚本文件存在", script.exists(), str(script))
    if not script.exists():
        return

    result = run_script(case, env, script_path=script)
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
    args = parser.parse_args()

    check_static(args.project)
    if not args.skip_run:
        check_run(args.project, args.case)

    failed = [name for name, ok in CHECKS if not ok]
    print(f"\n结果：{len(CHECKS) - len(failed)}/{len(CHECKS)} 通过")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
