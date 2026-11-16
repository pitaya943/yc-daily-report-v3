# 讓這個目錄的 feature 取得共用 fixture 與步驟（其他 feature 目錄自行 import，見 steps.py 的說明）
from tests.steps.common.steps import *  # noqa: F401,F403
