# Register / refresh the Windows Task Scheduler task that samples the
# five-platform boards + re-renders the 55188 ld change-points view every
# 3 minutes across the pre-open window (run_hot_preopen_3min.bat =>
# run_hot_rank_daily.bat + run_hot_ld_timeline.bat).
#
#   trigger 1 : daily 09:00, repetition every 3 min, duration 25 min
#               -> 09:00 09:03 09:06 09:09 09:12 09:15 09:18 09:21 09:24
#                  (the 10 min cadence of HotRankTDX_Intraday only ever
#                   lands on 09:00 / 09:10 / 09:20, which is why the
#                   change-points table used to show a single pre-open row)
#   trigger 2 : daily 09:26:56, single shot
#               -> tail sample; render-only, because the data point itself
#                  is produced by the forced 09:26:50 pass of
#                  HotRankTDX_Intraday (see run_hot_preopen_3min.bat)
#   trigger 3 : at logon, single shot
#               -> the whole chain (fetch + render + PROGRAM 1's 551883
#                  append) also fires right after the Administrator logs
#                  on, so a fresh sample exists without waiting for 09:00.
#   action    : wscript.exe run_hidden.vbs "<run_hot_preopen_3min.bat>"
#               -> SILENT. The task principal has to stay interactive, so
#                  a direct .bat action would pop a console window on the
#                  desktop on every trigger; wscript.exe with window style
#                  0 hides it (see run_hidden.vbs). run_hidden.vbs waits
#                  for the .bat to finish, so the Queue policy below still
#                  sees the task as running and nothing gets dropped.
#   principal : the logged-on Administrator, InteractiveToken -> the fetch
#               chain needs a real desktop for the Playwright/OCR JYGS pass,
#               exactly like HotRankTDX_Intraday. Sitting at the login
#               screen = the JYGS step degrades to its cache.
#   policy    : Queue (a slow pass is never silently dropped, the next tick
#               queues behind it), 10 min cap, StartWhenAvailable
#
# This task is ADDITIVE: it registers a new task and touches nothing else.
# HotRankTDX_Intraday (10 min, all day) and HotLdTimeline (10 min render)
# stay exactly as they are, so the window can be switched off with -Remove
# without disturbing the all-day pipeline.
#
# Usage (PowerShell; registering a task may require an elevated window):
#   powershell -ExecutionPolicy Bypass -File .\register_hot_preopen_task.ps1
#   powershell -ExecutionPolicy Bypass -File .\register_hot_preopen_task.ps1 -Remove
#
# Manual run / inspect:
#   Start-ScheduledTask  -TaskName HotPreopen3Min
#   Get-ScheduledTask    -TaskName HotPreopen3Min | Get-ScheduledTaskInfo

param([switch]$Remove)

$ErrorActionPreference = "Stop"

$TaskName = "HotPreopen3Min"
$Dir = $PSScriptRoot
$Bat = Join-Path $Dir "run_hot_preopen_3min.bat"
$Vbs = Join-Path $Dir "run_hidden.vbs"
$Wscript = Join-Path $env:SystemRoot "System32\wscript.exe"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "unregistered: $TaskName"
    return
}

if (-not (Test-Path $Bat)) { throw "missing launcher: $Bat" }
if (-not (Test-Path $Vbs)) { throw "missing silent wrapper: $Vbs" }
if (-not (Test-Path $Wscript)) { throw "missing wscript.exe: $Wscript" }

# launch through the silent wrapper, NOT the .bat directly (see "action" above)
$action = New-ScheduledTaskAction -Execute $Wscript `
        -Argument "`"$Vbs`" `"$Bat`"" -WorkingDirectory $Dir

# --- trigger 1: daily 09:00, every 3 min, for the next 25 min --------------
# A -Daily trigger cannot take a repetition directly, so build it on a
# throw-away -Once trigger and graft it onto the daily one.
$grid = New-ScheduledTaskTrigger -Daily -At "09:00"
$grid.Repetition = (New-ScheduledTaskTrigger -Once -At "09:00" `
        -RepetitionInterval (New-TimeSpan -Minutes 3) `
        -RepetitionDuration (New-TimeSpan -Minutes 25)).Repetition

# --- trigger 2: the tail sample --------------------------------------------
$tail = New-ScheduledTaskTrigger -Daily -At "09:26:56"

# --- trigger 3: at logon ---------------------------------------------------
# so the chain runs once as soon as the Administrator is logged on.
$logon = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet -MultipleInstances Queue `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd

# the fetch chain needs the desktop (Playwright/OCR JYGS pass), same as
# HotRankTDX_Intraday -> InteractiveToken of the logged-on Administrator
$principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" `
        -LogonType Interactive

Register-ScheduledTask -TaskName $TaskName -Action $action `
        -Trigger @($grid, $tail, $logon) -Settings $settings -Principal $principal `
        -Description "Pre-open window: run_hot_preopen_3min.bat every 3 min 09:00-09:24 + a 09:26:56 tail render + one run at logon (fetch five platforms then re-render the 55188 ld change-points table/board and append PROGRAM 1's top3 to 551883.blk)" `
        -Force | Out-Null

Write-Host "registered: $TaskName"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State | Format-List
(Get-ScheduledTask -TaskName $TaskName).Actions |
    Select-Object Execute, Arguments, WorkingDirectory | Format-List
(Get-ScheduledTask -TaskName $TaskName).Triggers |
    Select-Object CimClass, StartBoundary, Enabled, Repetition | Format-List
(Get-ScheduledTask -TaskName $TaskName).Principal |
    Select-Object UserId, LogonType | Format-List
(Get-ScheduledTask -TaskName $TaskName).Settings |
    Select-Object MultipleInstances, ExecutionTimeLimit, StartWhenAvailable |
    Format-List
