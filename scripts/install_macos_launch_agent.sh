#!/bin/zsh

set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    print -u2 "this installer only supports macOS"
    exit 1
fi

project_root="$(cd "$(dirname "$0")/.." && pwd)"
label="com.lxy.agent-trending-daily"
user_id="$(/usr/bin/id -u)"
keychain_account="$(/usr/bin/id -un)"
launch_agents_dir="$HOME/Library/LaunchAgents"
target_plist="$launch_agents_dir/$label.plist"
template_plist="$project_root/config/macos/$label.plist"

dashscope_api_key="${DASHSCOPE_API_KEY:-}"
dashscope_workspace_id="${DASHSCOPE_WORKSPACE_ID:-}"
if [[ -z "$dashscope_api_key" ]]; then
    dashscope_api_key="$(
        /usr/bin/security find-generic-password \
            -a "$keychain_account" \
            -s "agent-trending-daily/DASHSCOPE_API_KEY" \
            -w
    )"
fi
if [[ -z "$dashscope_workspace_id" ]]; then
    dashscope_workspace_id="$(
        /usr/bin/security find-generic-password \
            -a "$keychain_account" \
            -s "agent-trending-daily/DASHSCOPE_WORKSPACE_ID" \
            -w
    )"
fi
: "${dashscope_api_key:?DASHSCOPE_API_KEY is required}"
: "${dashscope_workspace_id:?DASHSCOPE_WORKSPACE_ID is required}"

/usr/bin/security add-generic-password \
    -U \
    -a "$keychain_account" \
    -s "agent-trending-daily/DASHSCOPE_API_KEY" \
    -w "$dashscope_api_key" \
    -T /usr/bin/security >/dev/null
/usr/bin/security add-generic-password \
    -U \
    -a "$keychain_account" \
    -s "agent-trending-daily/DASHSCOPE_WORKSPACE_ID" \
    -w "$dashscope_workspace_id" \
    -T /usr/bin/security >/dev/null

/bin/mkdir -p "$launch_agents_dir" "$project_root/logs"
if /bin/launchctl print "gui/$user_id/$label" >/dev/null 2>&1; then
    /bin/launchctl bootout "gui/$user_id/$label"
fi

/usr/bin/install -m 600 "$template_plist" "$target_plist"
/usr/bin/plutil -replace ProgramArguments \
    -json "[\"/bin/zsh\",\"$project_root/scripts/run_daily_macos.sh\"]" "$target_plist"
/usr/bin/plutil -replace WorkingDirectory -string "$project_root" "$target_plist"
/usr/bin/plutil -replace StandardOutPath \
    -string "$project_root/logs/launchd.out.log" "$target_plist"
/usr/bin/plutil -replace StandardErrorPath \
    -string "$project_root/logs/launchd.err.log" "$target_plist"

/bin/chmod 700 "$project_root/scripts/run_daily_macos.sh"
/bin/launchctl bootstrap "gui/$user_id" "$target_plist"
/bin/launchctl enable "gui/$user_id/$label"
/bin/launchctl print "gui/$user_id/$label" >/dev/null

timezone_path="$(/usr/bin/readlink /etc/localtime || true)"
if [[ "$timezone_path" != *"/Asia/Shanghai" ]]; then
    print -u2 "warning: launchd uses the Mac local timezone; current timezone is not Asia/Shanghai"
fi

print "installed $label; next scheduled run is 09:00 Mac local time"
