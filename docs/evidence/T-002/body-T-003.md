## 證據

完整輸出在 `docs/evidence/T-003/`：`00-red.txt`、`01-migration.txt`、`02-green.txt`、`03-full-suite.txt`、`04-mutation.txt`。

**先紅**（模組不存在，不是步驟寫錯）：
```
$ python3 -m pytest tests/unit/core tests/steps/common -q
E   ModuleNotFoundError: No module named 'app.core.outcomes'
E   ImportError: cannot import name 'audit' from 'app.core'
ERROR tests/unit/core/test_audit.py / test_outcomes.py / test_permissions.py / tests/steps/common/test_common_steps.py
4 errors in 0.08s
```

## Milestone 報告

`docs/milestones/M0.html`（由 Chief 撰寫）。
