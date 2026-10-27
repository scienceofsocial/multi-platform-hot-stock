# Register / refresh the Windows Task Scheduler task that refreshes the
# Eastmoney "leading concept boards" file (run_em_concept_daily.bat).
#
#   REGISTERED on 2026-09-24 (task EMLeadConcept, State=Ready; first manual
#   run LastTaskResult=0). Re-running this script refreshes/overwrites the task.
#
#   trigger 1 : daily at 00:00, repetition every 10 min, duration 1 day
#               -> same "all day, every day" spirit as HotRankTDX_Intraday:
#                  _em_lead_concept.json is then never more than 10 min old,
#                  which is what the per-date archive relies on
#   trigger 2 : daily 09:26:50, single shot
#               -> one forced pass right before the 09:30 open
#   principal : LOCAL SYSTEM -> starts whether or not anybody is signed in
#               (no dependency on Winlogon auto-logon, unlike HotRankTDX_Intraday)
#   policy    : Queue (the fixed 09:26:50 run is never silently dropped, it
#               queues behind a still-running pass), 10 min cap, StartWhenAvailable
#
# Usage (PowerShell; registering a task may require an elevated window):
#   powershell -ExecutionPolicy Bypass -File .\register_em_concept_task.ps1
#   powershell -ExecutionPolicy Bypass -File .\register_em_concept_task.ps1 -Remove
#
# Manual run / inspect:
#   Start-ScheduledTask  -TaskName EMLeadConcept
#   Get-ScheduledTask    -TaskName EMLeadConcept | Get-ScheduledTaskInfo
#
# To narrow the window to the trading session only, replace the repetition of
# $window below with e.g. a 09:00 start and a 6h30m duration.

param([switch]$Remove)

$ErrorActionPreference = "Stop"

$TaskName = "EMLeadConcept"
$Dir = $PSScriptRoot
$Bat = Join-Path $Dir "run_em_concept_daily.bat"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "unregistered: $TaskName"
    return
}

if (-not (Test-Path $Bat)) { throw "missing launcher: $Bat" }

$action = New-ScheduledTaskAction -Execute $Bat -WorkingDirectory $Dir

# --- trigger 1: every 10 min, all day, every day ---------------------------
# A -Daily trigger cannot take a repetition directly, so build the repetition
# on a throw-away -Once trigger and graft it onto the daily one.
$window = New-ScheduledTaskTrigger -Daily -At "00:00"
$window.Repetition = (New-ScheduledTaskTrigger -Once -At "00:00" `
        -RepetitionInterval (New-TimeSpan -Minutes 10) `
        -RepetitionDuration (New-TimeSpan -Days 1)).Repetition

# --- trigger 2: one forced pass right before the open ----------------------
$preopen = New-ScheduledTaskTrigger -Daily -At "09:26:50"

$settings = New-ScheduledTaskSettingsSet -MultipleInstances Queue `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd

# headless Chrome (Playwright) + one HTTP request; no desktop, no user state
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount

Register-ScheduledTask -TaskName $TaskName -Action $action `
        -Trigger @($window, $preopen) -Settings $settings -Principal $principal `
        -Description "EM lead concept boards: run_em_concept_daily.bat every 10 min all day (+09:26:50 pre-open)" `
        -Force | Out-Null

Write-Host "registered: $TaskName"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State | Format-List
(Get-ScheduledTask -TaskName $TaskName).Triggers |
    Select-Object CimClass, StartBoundary, Enabled | Format-List
(Get-ScheduledTask -TaskName $TaskName).Principal |
    Select-Object UserId, LogonType | Format-List
(Get-ScheduledTask -TaskName $TaskName).Settings |
    Select-Object MultipleInstances, ExecutionTimeLimit, StartWhenAvailable |
    Format-List
