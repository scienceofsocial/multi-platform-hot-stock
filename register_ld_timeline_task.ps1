# Register / refresh the Windows Task Scheduler task that re-renders the
# 55188 "leading stock board" (sj88.ld) intraday change-points table
# (=> run_hot_ld_timeline.bat => a_render_ld_timeline.py).
#
#   trigger 1 : at system startup, repetition every 10 min, duration 1 day
#               -> "boot, then every 10 min" (the reason $AtStartup is used
#                  instead of a -Daily trigger: the table should start being
#                  refreshed the moment the box comes up, with no dependency
#                  on anybody signing in - LOCAL SYSTEM below)
#   trigger 2 : daily at 00:00, repetition every 10 min, duration 1 day
#               -> keeps the every-10-min cadence alive when the machine stays
#                  up longer than one day (a startup trigger's repetition does
#                  NOT survive past RepetitionDuration, and uptime is not
#                  bounded here)
#   principal : LOCAL SYSTEM -> starts whether or not anybody is signed in
#   policy    : Queue (never silently drop a tick while a pass is still
#               running), 10 min cap, StartWhenAvailable
#
# Read-only task: it only reads _hot_archive\hot_trace.jsonl (appended by
# a_archive_hot_snapshot.py inside run_hot_rank_daily.bat / HotRankTDX_Intraday)
# and overwrites the Markdown file. No board is fetched here, so this task
# never competes with the fetch pipeline for the same upstream sites.
#
# Usage (PowerShell; registering a task may require an elevated window):
#   powershell -ExecutionPolicy Bypass -File .\register_ld_timeline_task.ps1
#   powershell -ExecutionPolicy Bypass -File .\register_ld_timeline_task.ps1 -Remove
#
# Manual run / inspect:
#   Start-ScheduledTask  -TaskName HotLdTimeline
#   Get-ScheduledTask    -TaskName HotLdTimeline | Get-ScheduledTaskInfo

param([switch]$Remove)

$ErrorActionPreference = "Stop"

$TaskName = "HotLdTimeline"
$Dir = $PSScriptRoot
$Bat = Join-Path $Dir "run_hot_ld_timeline.bat"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "unregistered: $TaskName"
    return
}

if (-not (Test-Path $Bat)) { throw "missing launcher: $Bat" }

$action = New-ScheduledTaskAction -Execute $Bat -WorkingDirectory $Dir

# Repetition ("every 10 min for 1 day") can only be built on a trigger that
# supports it, and neither -AtStartup nor -Daily takes one directly - so build
# it once on a throw-away -Once trigger and graft it onto both real triggers.
$everyTen = (New-ScheduledTaskTrigger -Once -At "00:00" `
        -RepetitionInterval (New-TimeSpan -Minutes 10) `
        -RepetitionDuration (New-TimeSpan -Days 1)).Repetition

# --- trigger 1: system startup, then every 10 min for the next 24 h --------
$boot = New-ScheduledTaskTrigger -AtStartup
$boot.Repetition = $everyTen

# --- trigger 2: daily 00:00, same 10 min cadence --------------------------
$daily = New-ScheduledTaskTrigger -Daily -At "00:00"
$daily.Repetition = $everyTen

$settings = New-ScheduledTaskSettingsSet -MultipleInstances Queue `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount

Register-ScheduledTask -TaskName $TaskName -Action $action `
        -Trigger @($boot, $daily) -Settings $settings -Principal $principal `
        -Description "55188 ld board change-points: run_hot_ld_timeline.bat at startup and every 10 min (read-only render of hot_trace.jsonl)" `
        -Force | Out-Null

Write-Host "registered: $TaskName"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State | Format-List
(Get-ScheduledTask -TaskName $TaskName).Triggers |
    Select-Object CimClass, StartBoundary, Enabled, Repetition | Format-List
(Get-ScheduledTask -TaskName $TaskName).Principal |
    Select-Object UserId, LogonType | Format-List
(Get-ScheduledTask -TaskName $TaskName).Settings |
    Select-Object MultipleInstances, ExecutionTimeLimit, StartWhenAvailable |
    Format-List
