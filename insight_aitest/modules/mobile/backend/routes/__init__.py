# -*- coding: utf-8 -*-
"""mobile 模块路由汇总。"""

from fastapi import APIRouter

from .apps import router as apps_router
from .cases import router as cases_router
from .devices import router as devices_router
from .runs import router as runs_router

router = APIRouter()
router.include_router(apps_router)
router.include_router(devices_router)
router.include_router(cases_router)
router.include_router(runs_router)

__all__ = ["router"]
