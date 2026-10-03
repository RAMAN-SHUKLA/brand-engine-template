# trigger_workflow.ps1
# Uses the PAT already stored in Windows (from git credential manager) to trigger the post-queue workflow.
# No separate credentials needed - works as long as you can push to GitHub.
#
# Run manually:   .\scheduler\trigger_workflow.ps1            (repo is read from `git remote get-url origin`)
#                 .\scheduler\trigger_workflow.ps1 -Repo owner/name

param([string]$Repo = "")

if (-not $Repo) {
    $origin = git -C (Split-Path -Parent $PSScriptRoot) remote get-url origin 2>$null
    if ($origin -match "github\.com[:/](.+?)(\.git)?$") { $Repo = $Matches[1] }
}
if (-not $Repo) {
    Write-Error "Could not find the GitHub repo. Pass it explicitly: -Repo owner/name"
    exit 1
}
$REPO = $Repo
$WORKFLOW = "post-queue.yml"
$BRANCH = "main"

# -- Get token from Windows Credential Manager (same one git uses to push) --
$credInput = "protocol=https`nhost=github.com`n`n"
$credOutput = $credInput | git credential fill 2>$null
$token = ($credOutput -split "`n" | Where-Object { $_ -match "^password=" }) -replace "^password=", ""

if (-not $token) {
    Write-Error "No GitHub token found in Windows Credential Manager. Push to GitHub at least once to cache it."
    exit 1
}

# -- Call GitHub workflow_dispatch API --
$url = "https://api.github.com/repos/$REPO/actions/workflows/$WORKFLOW/dispatches"
$body = '{"ref":"' + $BRANCH + '"}'
$headers = @{
    "Authorization"        = "Bearer $token"
    "Accept"               = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"           = "brand-engine-local-trigger"
}

try {
    $response = Invoke-WebRequest -Uri $url -Method POST -Headers $headers -Body $body -ContentType "application/json" -ErrorAction Stop
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$ts] SUCCESS: HTTP $($response.StatusCode) - Workflow dispatched on $REPO"
    Add-Content -Path "$PSScriptRoot\..\data\trigger_log.txt" -Value "[$ts] dispatch OK HTTP $($response.StatusCode)"
} catch {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$ts] FAILED: $_"
    Add-Content -Path "$PSScriptRoot\..\data\trigger_log.txt" -Value "[$ts] dispatch FAILED: $_"
    exit 1
}
