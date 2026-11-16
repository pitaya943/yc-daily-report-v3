"""小組分配（REV-R10）：純函式，不讀資料庫、不讀時鐘。

數量以 tenth（0.1 只）的整數計，避免浮點誤差。
"""


def split(tenths: int, crew_size: int) -> list[int]:
    """把 tenths 平分給 crew_size 人，回傳依 crew 順序排列的份額（tenth）。

    最大餘數法在這裡退化成簡單版本：每人先拿 tenths // crew_size，
    剩下的 tenths % crew_size 個 tenth 依序各給最前面的人
    （提交者排第一，其後依 crew 順序）。因此：
      - 份額加總恆等於 tenths；
      - 最大與最小相差不超過 1 tenth；
      - 後面的人不會比前面的人多。
    """
    if crew_size < 1:
        raise ValueError("crew_size must be at least 1")
    if tenths < 0:
        raise ValueError("tenths must not be negative")
    base, remainder = divmod(tenths, crew_size)
    return [base + 1 if i < remainder else base for i in range(crew_size)]
