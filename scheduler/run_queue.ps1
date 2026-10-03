# Runs the post queue once. Meant to be called hourly by Windows Task Scheduler.
# Logs to data\queue_runner.log so you can see what happened while you were away.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm"
"[$stamp] run_queue start" | Out-File -Append -Encoding utf8 "$root\data\queue_runner.log"
& python cli.py queue run 2>&1 | Out-File -Append -Encoding utf8 "$root\data\queue_runner.log"
