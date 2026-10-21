param(
    [switch]$Force
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
$RunBat = Join-Path $RepoRoot "run.bat"
$WorkflowFile = Join-Path $RepoRoot ".github\workflows\publish_shorts.yml"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  LOCAL FALLBACK ONLY. Production runs in the cloud (see README)." -ForegroundColor Yellow
Write-Host "  Setting up Windows Task Scheduler for Finance Shorts Pro" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# Refuse to install if cloud workflow has uncommented schedule: unless -Force
if (Test-Path $WorkflowFile) {
    $hasCloudSchedule = Select-String -Path $WorkflowFile -Pattern "^\s*schedule:" -Quiet
    if ($hasCloudSchedule -and -not $Force) {
        Write-Host " [ABORT] Cloud schedule is enabled in .github/workflows/publish_shorts.yml!" -ForegroundColor Red
        Write-Host " Running local scheduler concurrently would cause duplicate uploads." -ForegroundColor Red
        Write-Host " Pass -Force to install local scheduler anyway." -ForegroundColor Yellow
        exit 1
    }
}

$Times = @(
    @{ Name = "FinanceShorts_09AM"; Time = "09:00" },
    @{ Name = "FinanceShorts_03PM"; Time = "15:00" },
    @{ Name = "FinanceShorts_08PM"; Time = "20:00" }
)

foreach ($entry in $Times) {
    $taskName = $entry.Name
    $triggerTime = $entry.Time

    $action = New-ScheduledTaskAction `
        -Execute $RunBat `
        -Argument "publish-next" `
        -WorkingDirectory $RepoRoot

    $trigger = New-ScheduledTaskTrigger -Daily -At $triggerTime

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -WakeToRun `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1)

    try {
        Register-ScheduledTask `
            -TaskName $taskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Description "Finance Shorts autonomous publishing trigger at $triggerTime IST (Local fallback)" `
            -Force | Out-Null

        Write-Host " [OK] Registered: $taskName -> Daily at $triggerTime IST" -ForegroundColor Green
    }
    catch {
        Write-Host " [FAIL] Could not register $taskName : $_" -ForegroundColor Red
    }
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Setup Complete! Local fallback tasks registered." -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
