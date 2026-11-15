"""完成條件 4、5：把 spec/features/*.feature 的每個 scenario 變成 pytest 測試。

執行哪些、略過哪些，由 tests/support/bdd_plugin.py 依 tests/implemented.txt 決定。
步驟實作放在 tests/steps/<feature ID>/，由 tests/conftest.py 載入。
"""
from pytest_bdd import scenarios

scenarios(".")  # bdd_features_base_dir = spec/features
