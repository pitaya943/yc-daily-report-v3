# 框架自己的 feature（不是 spec）：驗證 T-003 完成條件 4——共用步驟對真的 HTTP 請求有效。
# 測試專用的路由在 test_common_steps.py 內掛上，不屬於產品程式。
Feature: Common steps

  Scenario: A rejection with a full message changes nothing
    When a USER submits a fourth report on the same day
    Then the request is rejected as CONFLICT with message "每日最多只能送出 3 筆回報"
    And nothing is written

  Scenario: A rejection without a spec message carries no message
    When a visitor requests any protected action
    Then the request is rejected as UNAUTHENTICATED
    And no audit row is written
    And nothing is written

  Scenario: A forbidden request writes only the ACCESS_DENIED row
    When "Wen" confirms a report directly
    Then the request is rejected as FORBIDDEN
    And an audit row "ACCESS_DENIED" is written with actor "Wen"
    And nothing is written except an audit row "ACCESS_DENIED" with actor "Wen"

  Scenario: An accepted request writes its audit row with the actor
    When "Admin1" confirms a report directly
    Then an audit row "REPORT_CONFIRM" is written with actor "Admin1"
