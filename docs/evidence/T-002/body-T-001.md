## 證據

條件 1～7 的輸出節錄自 `7be4c5f`（之後這些部分沒有變動）；條件 8 與修正第 2 輪的輸出節錄自 HEAD `3e6b764`。完整輸出在 `docs/evidence/T-001/`（沒有畫面，不需要截圖）。

**先紅**（`00-red.txt`；`app/` 不存在時）
```
$ python3 -m pytest -q
E   ModuleNotFoundError: No module named 'app.main'
E   ModuleNotFoundError: No module named 'app.core.clock'
E   ModuleNotFoundError: No module named 'tests.support.implemented'
E   ModuleNotFoundError: No module named 'app.core.db'
4 errors in 0.49s
```

## Milestone 報告

`docs/milestones/M0.html`（由 Chief 撰寫）
