#!/usr/bin/env bash
#
# Start Razorwire at login and keep it running.
#
#     bash scripts/autostart.sh on      install and start now
#     bash scripts/autostart.sh off     stop and uninstall
#     bash scripts/autostart.sh status  is it running, and on what URL
#
# A launchd LaunchAgent wrapping scripts/share.sh — macOS's own supervisor, so there
# is no pm2/supervisord/screen to install or babysit.
#
# An Agent rather than a Daemon: it runs as you, at login, which is what lets it
# reach the aidocs CLI's Google session in ~/.config/aidocs. A root Daemon at boot
# cannot see that, and every document fetch would 401.
#
# The paths are generated here rather than committed, because this repo is public
# and a plist is nothing but absolute paths.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
label="com.razorwire.share"
plist="$HOME/Library/LaunchAgents/$label.plist"
state="$HOME/.razorwire"
target="gui/$(id -u)"

case "${1:-on}" in
on)
  mkdir -p "$HOME/Library/LaunchAgents" "$state"

  cat >"$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$label</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$repo/scripts/share.sh</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$repo</string>

    <key>RunAtLoad</key>
    <true/>

    <!-- Restart if it dies. A quick tunnel dropped by a long sleep takes the whole
         script with it, and not having to notice is the point of this agent. The
         restart mints a NEW tunnel hostname, so \$HOME/.razorwire/urls.txt becomes
         the only record of the current link. -->
    <key>KeepAlive</key>
    <true/>

    <!-- Without this, a script that fails on startup respawns in a tight loop. -->
    <key>ThrottleInterval</key>
    <integer>30</integer>

    <!-- launchd hands over a near-empty PATH. Every entry is load-bearing:
         cloudflared, node and ffmpeg in Homebrew, aidocs in ~/.local/bin. -->
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin</string>
        <key>HOME</key>
        <string>$HOME</string>
    </dict>

    <key>StandardOutPath</key>
    <string>$state/agent.log</string>
    <key>StandardErrorPath</key>
    <string>$state/agent.log</string>
</dict>
</plist>
PLIST

  # bootout first so re-running this picks up an edited plist instead of silently
  # keeping the old one loaded.
  launchctl bootout "$target/$label" 2>/dev/null || true
  launchctl bootstrap "$target" "$plist"
  echo "installed $plist"
  echo "starting… the URL takes ~60s (tunnels, then a production build)"
  echo "watch:  tail -f $state/agent.log"
  echo "url:    cat $state/urls.txt"
  ;;

off)
  launchctl bootout "$target/$label" 2>/dev/null || true
  rm -f "$plist"
  echo "uninstalled. Razorwire will not start at login."
  echo "note: this does not stop a copy you started by hand."
  ;;

status)
  if launchctl print "$target/$label" >/dev/null 2>&1; then
    launchctl print "$target/$label" | grep -E '^\s+(state|pid|last exit code) ' || true
  else
    echo "not loaded"
  fi
  echo "--- current urls ---"
  cat "$state/urls.txt" 2>/dev/null || echo "none recorded yet"
  ;;

*)
  echo "usage: $0 [on|off|status]" >&2
  exit 1
  ;;
esac
