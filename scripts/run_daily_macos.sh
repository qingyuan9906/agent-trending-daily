#!/bin/zsh

set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
error_log="$project_root/logs/launchd.err.log"
keychain_account="$(/usr/bin/id -un)"
notifier="$project_root/scripts/notify_macos.applescript"
run_id="$(TZ=Asia/Shanghai date +%Y%m%dT%H%M%S)-$$"

log_stage() {
    local stage="$1"
    shift
    print -u2 "[$(TZ=Asia/Shanghai date '+%Y-%m-%dT%H:%M:%S%z')] run=$run_id stage=$stage $*"
}

retry_command() {
    local stage="$1"
    local attempts="$2"
    local delay_seconds="$3"
    shift 3
    local attempt
    for (( attempt = 1; attempt <= attempts; attempt++ )); do
        log_stage "$stage" "attempt=$attempt/$attempts"
        if "$@"; then
            log_stage "$stage" "status=success"
            return 0
        fi
        log_stage "$stage" "status=failed"
        if (( attempt < attempts )); then
            /bin/sleep "$delay_seconds"
        fi
    done
    return 1
}

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
        log_stage complete "status=failed exit_code=$exit_status"
        notify_user failure "$error_log"
    fi
}

trap handle_exit EXIT

cd "$project_root"
if [[ -n "$(git status --porcelain)" ]]; then
    log_stage validate "scheduled run requires a clean Git worktree"
    exit 1
fi

log_stage start "status=running"
network_route="$(/usr/bin/python3 "$project_root/scripts/network_preflight.py")"
if [[ "$network_route" != "DIRECT" ]]; then
    export HTTP_PROXY="$network_route"
    export HTTPS_PROXY="$network_route"
    export http_proxy="$network_route"
    export https_proxy="$network_route"
    export NO_PROXY="localhost,127.0.0.1,::1"
    export no_proxy="$NO_PROXY"
    log_stage preflight "selected_route=proxy"
else
    unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
    log_stage preflight "selected_route=direct"
fi

retry_command git_pull 3 20 git pull --ff-only
retry_command uv_sync 3 20 uv sync --locked

credential_block="$(
    printf 'protocol=https\nhost=github.com\n\n' \
        | GIT_TERMINAL_PROMPT=0 git credential fill 2>/dev/null \
        || true
)"
github_token="$(
    printf '%s\n' "$credential_block" \
        | awk -F= '$1 == "password" {print substr($0, index($0, "=") + 1)}'
)"

if [[ -n "$github_token" ]]; then
    export GITHUB_TOKEN="$github_token"
fi

retry_command collect 2 300 uv run agent-trending collect
run_date="$(TZ=Asia/Shanghai date +%F)"
observation_path="$project_root/data/observations/$run_date.json"
test -f "$observation_path"
git add "data/observations/$run_date.json"
if ! git diff --cached --quiet; then
    git commit -m "chore(observation): collect $run_date trending data"
fi
if [[ -n "$(git rev-list '@{upstream}..HEAD')" ]]; then
    retry_command git_push 3 20 git push origin HEAD
fi

if [[ "$(TZ=Asia/Shanghai date +%u)" == "1" ]]; then
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
    test -n "$DASHSCOPE_API_KEY"
    test -n "$DASHSCOPE_WORKSPACE_ID"
    retry_command weekly_pipeline 2 300 uv run agent-trending publish-weekly

    report_path="$project_root/reports/$run_date.html"
    test -f "$report_path"
    git add \
        "data/$run_date.json" \
        "reports/$run_date.md" \
        "reports/$run_date.html" \
        reports/latest.md \
        reports/latest.html
    if ! git diff --cached --quiet; then
        git commit -m "chore(report): update $run_date weekly trending digest"
    fi
    if [[ -n "$(git rev-list '@{upstream}..HEAD')" ]]; then
        retry_command git_push 3 20 git push origin HEAD
    fi
fi

trap - EXIT
if [[ -n "${report_path:-}" ]]; then
    log_stage complete "status=success report=$report_path"
    notify_user success "$report_path"
else
    log_stage complete "status=success observation=$observation_path"
fi
