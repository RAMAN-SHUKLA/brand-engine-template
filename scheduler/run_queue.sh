#!/usr/bin/env sh
# Runs the post queue once. macOS/Linux equivalent of run_queue.ps1, meant to be called by cron.
# Logs to data/queue_runner.log so you can see what happened while you were away.
#
# Add to your crontab (`crontab -e`) to run every 15 minutes:
#   */15 * * * * /path/to/brand-engine/scheduler/run_queue.sh
#
# The machine must be awake at post time. Items more than `publish.queue.max_late_hours` late are skipped.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
PY="${PYTHON:-python3}"
[ -x "$ROOT/.venv/bin/python" ] && PY="$ROOT/.venv/bin/python"
echo "[$(date '+%Y-%m-%d %H:%M')] run_queue start" >> "$ROOT/data/queue_runner.log"
"$PY" cli.py queue run >> "$ROOT/data/queue_runner.log" 2>&1
