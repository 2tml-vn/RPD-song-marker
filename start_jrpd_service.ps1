# JRPD Startup Script
# This script starts the JRPD service in the background

$scriptPath = "D:\rpd\label_marks_complete_service.py"
$logPath = "D:\rpd\jrpd_service.log"

# Create a background job to run the Python service
$job = Start-Job -ScriptBlock {
    param($scriptPath, $logPath)
    
    # Change to the script directory and start the Python service
    Set-Location -Path (Split-Path $scriptPath -Parent)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "python"
    $psi.Arguments = "`"$scriptPath`""
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    
    $process = [System.Diagnostics.Process]::Start($psi)
    $process.WaitForExit()
    
    # Log the exit code
    "$([DateTime]::Now): Service exited with code $($process.ExitCode)" | Out-File -Append $logPath
}

Write-Host "JRPD service started in background job."
Write-Host "Job ID: $($job.Id)"
Write-Host "To view output: Receive-Job -Id $($job.Id)"
Write-Host "To stop the service: Stop-Job -Id $($job.Id); Remove-Job -Id $($job.Id)"