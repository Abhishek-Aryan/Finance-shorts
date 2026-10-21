# Uninstall Windows Scheduled Tasks for Finance Shorts Pro

$Tasks = @("FinanceShorts_09AM", "FinanceShorts_03PM", "FinanceShorts_08PM")

foreach ($t in $Tasks) {
    $existing = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $t -Confirm:$false
        Write-Host " [REMOVED] $t" -ForegroundColor Yellow
    } else {
        Write-Host " [INFO] $t not found." -ForegroundColor DarkGray
    }
}

Write-Host "Finance Shorts scheduled tasks uninstallation check complete." -ForegroundColor Green
