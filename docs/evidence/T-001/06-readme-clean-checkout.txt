# 乾淨 checkout（commit 6254736）；資料庫資料目錄事先刪除，venv 全新
++ scripts/dev/install-postgres
已安裝：postgres (PostgreSQL) 17.12 (Ubuntu 17.12-1.pgdg24.04+1)
++ grep -v notice
++ pip install -q -e '.[dev]'

++ scripts/dev/db-start
初始化資料目錄 /var/lib/yc-pg17
PostgreSQL 已啟動（port 5433）
已建立資料庫 yc
DATABASE_URL=postgresql://postgres@127.0.0.1:5433/yc
++ scripts/dev/migrate
套用 0001_init_accounts.sql
migration 完成
++ python -m pytest
============================= test session starts ==============================
platform linux -- Python 3.13.18, pytest-9.2.0, pluggy-1.7.0
rootdir: <clean-checkout-parent>/clean2
configfile: pyproject.toml
testpaths: tests
plugins: bdd-9.0.1, anyio-4.16.0
collected 510 items

tests/integration/test_smoke.py .....                                    [  0%]
tests/integration/test_world_bdd.py ..                                   [  1%]
tests/test_spec.py sssssssssssssssssssssssssssssssssssssssssssssssssssss [ 11%]
ssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss [ 25%]
ssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss [ 40%]
ssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss [ 54%]
ssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss [ 68%]
ssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss [ 82%]
ssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss   [ 96%]
tests/unit/test_background_parser.py .                                   [ 96%]
tests/unit/test_clock.py ......                                          [ 97%]
tests/unit/test_implemented_mechanism.py ....                            [ 98%]
tests/unit/test_local_only.py .........                                  [100%]

======================= 27 passed, 483 skipped in 0.85s ========================
++ set +x
