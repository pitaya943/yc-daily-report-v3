"""應用程式進入點。

`create_app()` 自動掃描 app/modules/<模組>/<feature>/router.py，註冊其中名為 `router` 的 APIRouter。
新增 feature 只要放進約定的目錄，不必回來改這個檔案（也就不會讓平行的 ticket 互相衝突）。
"""
from __future__ import annotations

import importlib
import pkgutil

from fastapi import APIRouter, FastAPI

import app.modules as modules_pkg


def discover_routers() -> list[APIRouter]:
    routers: list[APIRouter] = []
    for module_info in pkgutil.iter_modules(modules_pkg.__path__):
        if not module_info.ispkg:
            continue
        module_pkg = importlib.import_module(f"{modules_pkg.__name__}.{module_info.name}")
        for feature_info in pkgutil.iter_modules(module_pkg.__path__):
            if not feature_info.ispkg:
                continue
            router_name = f"{module_pkg.__name__}.{feature_info.name}.router"
            try:
                mod = importlib.import_module(router_name)
            except ModuleNotFoundError as e:
                # 該 feature 沒有 router.py 是正常的；router.py 內部 import 失敗則必須讓它爆出來
                if e.name == router_name:
                    continue
                raise
            router = getattr(mod, "router", None)
            if isinstance(router, APIRouter):
                routers.append(router)
    return routers


def create_app() -> FastAPI:
    app = FastAPI(title="yc-daily-report")
    for router in discover_routers():
        app.include_router(router)
    return app


app = create_app()
