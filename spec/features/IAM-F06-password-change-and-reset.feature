# IAM-F06 密碼變更與重設
# 對照 v2 spec：B-008
# 共用的固定資料見 spec/background.md；結果類別與寫作規約見 spec/README.md。
@IAM-F06 @B-008
Feature: Password change and reset

  Rule: IAM-R30 Changing one's own password needs the current password and a matching confirmation

    Scenario Outline: Own password change
      Given "<who>" is signed in
      When "<who>" changes their password with current "<current>", new "<new>", confirmation "<confirm>"
      Then the outcome is <outcome> with message "<message>"

      Examples:
        | who    | current | new      | confirm  | outcome  | message                    |
        | Wen    | correct | newpass1 | newpass1 | accepted |                            |
        | Wen    | wrong   | newpass1 | newpass1 | INVALID  | 目前密碼不正確             |
        | Wen    | correct | newpass1 | newpass2 | INVALID  | 兩次輸入的密碼不一致       |
        | Wen    | correct | short    | short    | INVALID  | 密碼長度須為 6 至 30 個字  |
        | Admin1 | correct | newpass1 | newpass1 | accepted |                            |
        | Admin1 | wrong   | newpass1 | newpass1 | INVALID  | 目前密碼不正確             |

    @provisional @Q-053
    Scenario: The owner also enters the current password
      Given "Kuei" is signed in
      When "Kuei" changes their password with a wrong current password
      Then the request is rejected as INVALID with message "目前密碼不正確"

    Scenario: A password change is audited without the password
      Given "Wen" is signed in
      When "Wen" changes their password successfully
      Then an audit row "PASSWORD_CHANGE" is written with actor "Wen"
      And the audit description contains neither the old nor the new password

  Rule: IAM-R31 An administrator resets a USER password without the current password

    Scenario: Reset
      Given "Admin1" is signed in
      When "Admin1" resets the password of "Wen" to "newpass1"
      Then "Wen" can sign in with "newpass1"
      And an audit row "PASSWORD_CHANGE" is written with actor "Admin1"

  Rule: IAM-R32 There is no self-service password recovery

    Scenario: Forgotten password
      When a visitor asks to recover the password of "Wen"
      Then no such action exists
      # 員工請管理員重設；owner 的密碼在系統外重設（Q-046）。

  Rule: IAM-R33 A password change ends the account's other sessions; a reset ends all of them

    # D-123：自己改密碼時保留目前這個 session；被管理員重設時，該帳戶全部的 session 都結束。
    Scenario: Changing one's own password keeps only the current session
      Given "Wen" is signed in on two devices
      When "Wen" changes their password successfully on the first device
      Then the first device of "Wen" can still make protected requests
      And a protected request from the second device of "Wen" is rejected as UNAUTHENTICATED

    Scenario: A reset ends every session of the account
      Given "Wen" is signed in on two devices
      When "Admin1" resets the password of "Wen" to "newpass1"
      Then a protected request from either device of "Wen" is rejected as UNAUTHENTICATED

  Rule: IAM-R34 A wrong current password counts toward the sign-in lockout

    # D-124：改密碼時輸入錯誤的目前密碼，與登入共用同一個失敗計數與鎖定（IAM-R04、R05）。
    Scenario: The fifth wrong password across sign-in and password change locks the account
      Given "Wen" is signed in
      And "Wen" has 4 failed sign-ins in the last 15 minutes
      When "Wen" changes their password with a wrong current password
      Then the request is rejected as LOCKED with message "密碼錯誤次數過多，請在 15 分鐘後再試"
      And an audit row "ACCOUNT_LOCKOUT" is written with actor SYSTEM

    Scenario: A locked account cannot change its password
      Given "Wen" is signed in
      And "Wen" was locked 5 minutes ago
      When "Wen" changes their password with current "correct", new "newpass1", confirmation "newpass1"
      Then the request is rejected as LOCKED with message "密碼錯誤次數過多，請在 15 分鐘後再試"
      And nothing is written
