<#
Installs the Followthrough engine to start automatically when you sign in to Windows.
Run from PowerShell:   .\engine\install-windows.ps1
Remove it again with:  .\engine\install-windows.ps1 -Uninstall
#>
param([switch]$Uninstall)

$TaskName = "Followthrough Engine"
$Root = Split-Path -Parent $PSScriptRoot

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed '$TaskName'. Stop any running engine with Ctrl+C or Task Manager (pythonw.exe)."
    exit 0
}

$python = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $python) { Write-Error "Python was not found on PATH."; exit 1 }

$action   = New-ScheduledTaskAction -Execute $python -Argument "run.py engine" -WorkingDirectory $Root
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 `
            -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed '$TaskName'. The engine now starts when you sign in and is running now."
Write-Host "Dashboard: http://127.0.0.1:8765   Log: $Root\runs\engine.log"
