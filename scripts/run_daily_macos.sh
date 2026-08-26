#!/bin/zsh

set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
error_log="$project_root/logs/launchd.err.log"
keychain_account="$(/usr/bin/id -un)"
notifier="$project_root/scripts/notify_macos.applescript"

notify_user() {
    local notification_kind="$1"
    local target_path="$2"
    local selected_path
    selected_path="$(/usr/bin/osascript "$notifier" "$notification_kind" "$target_path" 2>/dev/null || true)"
    if [[ -n "$selected_path" && "$selected_path" != "none" ]]; then
        /usr/bin/open "$selected_path"
    fi
}

handle_exit() {
    local exit_status=$?
    if (( exit_status != 0 )); then
        notify_user failure "$error_log"
    fi
}

trap handle_exit EXIT

export DASHSCOPE_API_KEY="$(
    /usr/bin/security find-generic-password \
        -a "$keychain_account" \
        -s "agent-trending-daily/DASHSCOPE_API_KEY" \
        -w
)"
export DASHSCOPE_WORKSPACE_ID="$(
    /usr/bin/security find-generic-password \
        -a "$keychain_account" \
        -s "agent-trending-daily/DASHSCOPE_WORKSPACE_ID" \
        -w
)"

credential_block="$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill)"
export GITHUB_TOKEN="$(
    printf '%s\n' "$credential_block" \
        | awk -F= '$1 == "password" {print substr($0, index($0, "=") + 1)}'
)"

test -n "$DASHSCOPE_API_KEY"
test -n "$DASHSCOPE_WORKSPACE_ID"
test -n "$GITHUB_TOKEN"

cd "$project_root"
if [[ -n "$(git status --porcelain)" ]]; then
    print -u2 "scheduled run requires a clean Git worktree"
    exit 1
fi

git pull --ff-only
uv sync --locked
uv run agent-trending run

run_date="$(TZ=Asia/Shanghai date +%F)"
report_path="$project_root/reports/$run_date.md"
test -f "$report_path"

git add "data/$run_date.json" "reports/$run_date.md" reports/latest.md
if ! git diff --cached --quiet; then
    git commit -m "chore(report): update $run_date trending digest"
    git push origin HEAD
fi

trap - EXIT
notify_user success "$report_path"
