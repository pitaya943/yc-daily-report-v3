# 框架自己的 feature（不是 spec）：驗證完成條件 4——每個 scenario 開始前資料庫是乾淨的 background。
Feature: Test world reset

  Scenario: A scenario can write to the database
    Given the database holds exactly the background accounts
    When a test account "Temp" is added
    Then the database holds 10 accounts

  Scenario: The next scenario starts from the background again
    Then the database holds exactly the background accounts
    And the clock reads "2026-11-15T10:00:00+08:00"
