# RPT-F03 歷史與匯出
# 對照 v2 spec：B-063
# 共用的固定資料見 spec/background.md；結果類別與寫作規約見 spec/README.md。
@RPT-F03 @B-063
Feature: History and export

  Rule: RPT-R20 A USER sees reports they submitted and reports they collaborated on

    Scenario: Own and collaborated rows
      Given "Wen" submitted R1 dated "2026-11-10"
      And "Wei" submitted R2 dated "2026-11-12" with collaborator "Wen"
      And "Wei" submitted R3 dated "2026-11-13" with no collaborator
      When "Wen" opens history
      Then the list is R2, R1 in that order
      And R2 is labelled "共作（Wei 回報）"

    Scenario: Status wording
      Given "Wen" has one PENDING, one CONFIRMED, and one REJECTED report
      When "Wen" opens history
      Then the statuses read "未確認", "已確認", "已駁回"

  Rule: RPT-R21 Administrators see all ordinary reports on one page and big-meter reports on another

    Scenario: Ordinary history
      Given reports by "Wen", "Nan", and "Big"
      When "Admin1" opens ordinary history
      Then the list contains the reports of "Wen" and "Nan" only

    Scenario: Big-meter history
      Given reports by "Wen", "Nan", and "Big"
      When "Admin1" opens big-meter history
      Then the list contains the report of "Big" only

    Scenario Outline: Administrator filters
      Given R1 by "Wen" dated "2026-11-10", R2 by "Nan" dated "2026-11-12" with a custom item, R3 by "Wei" dated "2026-11-13" with collaborator "Wen"
      When "Admin1" filters ordinary history by <filter>
      Then the list is "<rows>"

      Examples:
        | filter                              | rows       |
        | dates 2026-11-11 to 2026-11-13      | R3, R2     |
        | account Wen                         | R3, R1     |
        | zone SOUTH                          | R2         |
        | has custom item                     | R2         |

  Rule: RPT-R22 An export contains exactly the filtered rows the person may see

    Scenario: USER export
      Given "Wen" can see 2 reports under the current filter
      When "Wen" exports history to Excel
      Then the file is .xlsx with 2 data rows
      And an audit row "EXPORT" is written with actor "Wen"

    Scenario Outline: Export columns
      When "Admin1" exports <page> history
      Then the columns are <columns>

      Examples:
        | page      | columns                                                                   |
        | ordinary  | date, account, the union of WEST and SOUTH items, custom item, confirmation |
        | big-meter | date, account, the BIG_METER items, custom item, confirmation             |

  Rule: RPT-R23 Filter values are validated

    Scenario Outline: Invalid filters
      When "Admin1" filters history by <filter>
      Then the request is rejected as INVALID with message "請輸入有效的篩選條件"

      Examples:
        | filter                 |
        | date "2026-13-40"      |
        | zone "EAST"            |
        | account "Nobody"       |
