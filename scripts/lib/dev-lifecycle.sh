#!/usr/bin/env bash
# Shared helpers for scripts/start-*-linux.sh / start-all-linux.sh /
# stop-all-linux.sh. Meant to be sourced, not executed directly.

# Terminate the process group recorded in pidfile $1 (if still alive), then
# remove the pidfile. Leg scripts write their own $$ to their pidfile right
# before the final `exec`, and are always run as their own process-group
# leader (either via interactive job control, or via start-all-linux.sh's
# `setsid`), so `-$pid` reliably reaches the whole subtree — e.g. uvicorn
# --reload's worker, or npm's vite child.
dev_stop_pidfile() {
  local pid_file="$1" pid
  [ -f "$pid_file" ] || return 0
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  rm -f "$pid_file"
  [ -n "${pid:-}" ] || return 0
  kill -0 "$pid" 2>/dev/null || return 0
  kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.5
  done
  kill -KILL "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
}

# Fallback cleanup for whatever is bound to TCP port $1 when there's no (or a
# stale) pidfile — e.g. a previous run that was killed out-of-band.
dev_stop_port() {
  local port="$1" pid
  while pid="$(ss -H -ltnp "sport = :${port}" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1)" && [ -n "$pid" ]; do
    kill -TERM "$pid" 2>/dev/null || true
    sleep 0.5
    kill -KILL "$pid" 2>/dev/null || true
  done
}

# Poll a URL until it answers 2xx/3xx, or time out.
dev_wait_http_ok() {
  local url="$1" timeout="${2:-90}" waited=0
  while [ "$waited" -lt "$timeout" ]; do
    curl -fsS -o /dev/null "$url" 2>/dev/null && return 0
    sleep 1
    waited=$((waited + 1))
  done
  return 1
}
