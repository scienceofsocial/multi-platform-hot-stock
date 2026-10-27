# Register / refresh the Windows Task Scheduler task that aggregates the
# 55188 leading-board (sj88.ld) change-points history into the statistics
# report (=> run_hot_ld_timeline_stats.bat => ld_timeline_stats.py).
#
#   trigger : (1) at system startup            -> refresh + backfill right
#                                                  after boot (user asked to
#                                                  "run at startup")
#             (2) daily at 15:10              -> after the intraday table has
#                                                 been rendered and the
#                                                 after-hours changes started
#                                                 landing
#             (3) daily at 17:20              -> end of day, after the fetch
#                                                 pipeline settles
#   principal : LOCAL SYSTEM -> runs whether or not anybody is signed in
#   policy    : IgnoreNew (the aggregation takes seconds; a second copy
#               would only fight over the same output file), 10 min cap,
#               StartWhenAvailable
#
# Read-only aggregation: it reads 龙头榜_变化时点_*.md, _hot_archive\hot_*.json
# and the local Tongdaxin day files. It never fetches any board, so it never
# competes with the fetch pipeline.
#
# Usage (PowerShell; registering a task may require an elevated window):
#   powershell -ExecutionPolicy Bypass -File .\register_ld_timeline_stats_task.ps1
#   powershell -ExecutionPolicy Bypass -File .\register_ld_timeline_stats_task.ps1 -Remove
#
# Manual run / inspect:
#   Start-ScheduledTask  -TaskName HotLdTimelineStats
#   Get-ScheduledTask    -TaskName HotLdTimelineStats | Get-ScheduledTaskInfo

param([switch]$Remove)

$ErrorActionPreference = "Stop"

$TaskName = "HotLdTimelineStats"
$Dir = $PSScriptRoot
$Bat = Join-Path $Dir "run_hot_ld_timeline_stats.bat"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "unregistered: $TaskName"
    return
}

if (-not (Test-Path $Bat)) { throw "missing launcher: $Bat" }

$action = New-ScheduledTaskAction -Execute $Bat -WorkingDirectory $Dir

# Boot trigger: fires right after the machine comes up. Delay 2 min so the
# disk / Tongdaxin day files are settled; StartWhenAvailable also covers a
# missed run. A boot trigger keeps firing across restarts without needing a
# login session (principal is LOCAL SYSTEM).
$t0 = New-ScheduledTaskTrigger -AtStartup
$t0.Delay = "PT2M"

$t1 = New-ScheduledTaskTrigger -Daily -At "15:10"
$t2 = New-ScheduledTaskTrigger -Daily -At "17:20"

$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount

Register-ScheduledTask -TaskName $TaskName -Action $action `
        -Trigger @($t0, $t1, $t2) -Settings $settings -Principal $principal `
        -Description "55188 ld board change-points statistics: run_hot_ld_timeline_stats.bat at startup (+2min), daily 15:10 and 17:20 (read-only aggregation)" `
        -Force | Out-Null

Write-Host "registered: $TaskName"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State | Format-List
(Get-ScheduledTask -TaskName $TaskName).Triggers |
    Select-Object CimClass, StartBoundary, Delay, Enabled | Format-List
(Get-ScheduledTask -TaskName $TaskName).Principal |
    Select-Object UserId, LogonType | Format-List
(Get-ScheduledTask -TaskName $TaskName).Settings |
    Select-Object MultipleInstances, ExecutionTimeLimit, StartWhenAvailable |
    Format-List
