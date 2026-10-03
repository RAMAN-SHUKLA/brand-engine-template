# Registers a Windows Scheduled Task (every 15 minutes) that runs the post queue.
# Run this ONCE from PowerShell (no admin needed for a per-user task):
#     powershell -ExecutionPolicy Bypass -File <path-to-brand-engine>\scheduler\register_windows_task.ps1
# Remove it later with:   schtasks /Delete /TN "brand-engine post queue" /F
#
# The PC must be on (or waking) at post time. If it was asleep, the runner posts the item on the next
# hour it runs, unless it is more than `publish.queue.max_late_hours` late (default 24), in which case it skips it.

$root   = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "scheduler\run_queue.ps1"
$action = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""

schtasks /Create /F /TN "brand-engine post queue" /TR $action /SC MINUTE /MO 15 /RL LIMITED
if ($LASTEXITCODE -eq 0) {
    Write-Host "Registered successfully. Runs every 15 minutes."
    Write-Host "Query with: schtasks /Query /TN `"brand-engine post queue`" /FO LIST"
}
