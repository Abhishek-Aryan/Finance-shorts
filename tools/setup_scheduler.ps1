# Windows Task Scheduler Setup for Finance Shorts Pro
# Sets up 3 daily automated triggers: 09:00 AM, 03:00 PM, and 08:00 PM IST

$TaskRoot = "C:\Users\Admin\finance.bat"
$LogPath = "C:\Users\Admin\.gemini\antigravity-ide\scratch\finance-shorts\logs\scheduler.log"

$Times = @(
    @{ Name = "FinanceShorts_09AM"; Time = "09:00" },
    @{ Name = "FinanceShorts_03PM"; Time = "15:00" },
    @{ Name = "FinanceShorts_08PM"; Time = "20:00" }
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Setting up Windows Task Scheduler for Finance Shorts Pro" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

foreach ($entry in $Times) {
    $taskName = $entry.Name
    $triggerTime = $entry.Time

    $action = New-ScheduledTaskAction `
        -Execute "cmd.exe" `
        -Argument "/c `"$TaskRoot`" publish-next >> `"$LogPath`" 2>&1" `
        -WorkingDirectory "C:\Users\Admin\.gemini\antigravity-ide\scratch\finance-shorts"

    $trigger = New-ScheduledTaskTrigger -Daily -At $triggerTime

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -WakeToRun

    try {
        Register-ScheduledTask `
            -TaskName $taskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Description "Finance Shorts autonomous publishing trigger at $triggerTime IST" `
            -Force | Out-Null

        Write-Host " [OK] Registered: $taskName -> Daily at $triggerTime IST" -ForegroundColor Green
    }
    catch {
        Write-Host " [FAIL] Could not register $taskName : $_" -ForegroundColor Red
    }
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Setup Complete! Tasks will run automatically every day." -ForegroundColor Green
Write-Host "  Trigger times: 09:00 AM, 3:00 PM, 8:00 PM IST" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan
