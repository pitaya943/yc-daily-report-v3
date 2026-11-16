#!/usr/bin/env bash
# 誤擋測試：fp.sh <ticket> <目標分支 commit> <PR head commit>
# 用目前 ticket/T-002 的 scripts/ci 與 workflow，對真實的 ticket PR 跑全部 10 項檢查。
set -uo pipefail
TID=$1; BASE=$2; HEAD=$3
REPO=$(git rev-parse --show-toplevel)
SP=$(cd "$(dirname "$0")" && pwd)   # 同目錄需要 body-<ticket>.md 與 logins-<ticket>.json（PR 說明的證據一節、API 的 author.login）
W=$(mktemp -d)/fp-$TID; git -C $REPO worktree prune
git -C $REPO worktree add -q --detach "$W/base" "$BASE"
# 目標分支加上「目前版本」的 ticket 檔（有 screens 欄位，D-040）；只在本機、不推送
cp $REPO/docs/tickets/$TID.md "$W/base/docs/tickets/$TID.md"
git -C "$W/base" -c user.name=bullet-bots -c user.email=354516064+bullet-bots@users.noreply.github.com \
  commit -q -am "local only: current $TID ticket file" 
BASE2=$(git -C "$W/base" rev-parse HEAD)
git -C $REPO worktree add -q --detach "$W/head" "$HEAD"
# head 上放 T-002 的檢查程式（未追蹤的檔案，不影響 git diff）
mkdir -p "$W/head/scripts/ci" "$W/head/.github/workflows"
cp $REPO/scripts/ci/*.py $REPO/scripts/ci/test-results $REPO/scripts/ci/ruff.toml "$W/head/scripts/ci/"; cp $REPO/.github/workflows/ci.yml "$W/head/.github/workflows/"
cd "$W/head"
export DATABASE_URL=postgresql://postgres@127.0.0.1:5433/yc CI_BASE_SHA=$BASE2 CI_HEAD_SHA=$HEAD \
  CI_BASE_REF=milestone/M0 CI_HEAD_REF=ticket/$TID CI_PR_BODY="$(cat $SP/body-$TID.md)" \
  YC_BASE_TEST_REPORT=$W/base-test-report.json YC_HEAD_TEST_REPORT=$W/head-test-report.json YC_RULE_REPORT=$W/rule-report.json
echo "== $TID：目標分支 $(git rev-parse --short $BASE)（+ 目前的 ticket 檔 → $(git rev-parse --short $BASE2)），PR head $(git rev-parse --short $HEAD)"
echo "== PR 修改的檔案：$(git diff --name-only $BASE2...$HEAD | wc -l) 個"
rc=0
for n in tests spec-readonly path-scope evidence migration-scope strings lint; do
  python3 scripts/ci/run.py $n | tail -3 || rc=1
done
scripts/ci/test-results "$W/base" "$YC_BASE_TEST_REPORT" | tail -1
scripts/ci/test-results "$W/head" "$YC_HEAD_TEST_REPORT" | tail -1
python3 scripts/ci/run.py no-weakened-tests | tail -3 || rc=1
python3 -m pytest -q -p scripts.ci.rule_report -p no:cacheprovider | tail -1
python3 scripts/ci/run.py done-when | tail -3 || rc=1
python3 scripts/ci/run.py commit-author --range $BASE..$HEAD --logins-file $SP/logins-$TID.json | tail -3 || rc=1
python3 -c "
import json; b=json.load(open('$YC_BASE_TEST_REPORT'))['tests']; h=json.load(open('$YC_HEAD_TEST_REPORT'))['tests']
p=lambda d: sum(v=='passed' for v in d.values())
print(f'== 結果報告：目標分支 {len(b)} 個 ID（{p(b)} passed），PR {len(h)} 個 ID（{p(h)} passed）')"
cd /; git -C $REPO worktree remove --force "$W/base"; git -C $REPO worktree remove --force "$W/head"
echo "== 結束碼：$rc"
