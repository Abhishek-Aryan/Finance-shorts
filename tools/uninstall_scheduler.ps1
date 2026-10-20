# Uninstall Windows Scheduled Tasks for Finance Shorts Pro

$Tasks = @("FinanceShorts_09AM", "FinanceShorts_03PM", "FinanceShorts_08PM")

foreach ($t in $Tasks) {
    try {
        Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host " [REMOVED] $t" -ForegroundColor Yellow
    }
    catch {
        Write-Host " [INFO] $t not found or already removed."
    }
}

Write-Host "All Finance Shorts scheduled tasks removed." -ForegroundColor Green
