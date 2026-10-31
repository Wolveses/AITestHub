# -*- coding: utf-8 -*-
"""AI 自动化脚本路由。"""

from fastapi import APIRouter

from .cases import router as cases_router
from .envs import router as envs_router

router = APIRouter()
router.include_router(cases_router)
router.include_router(envs_router)

__all__ = ["router"]
