# Register / refresh the Windows Task Scheduler task for PROGRAM 2:
# append the 3 codes currently shown as the last row of the
# a_render_ld_timeline.py change-points table into blocknew\55188.blk
# at three fixed slots per day (run_ld_top3_blk_551884.bat =>
# a_export_ld_top3_blk.py --blk ...\55188.blk).
#
#   trigger 1 : daily 09:00:09   (the opening sample)
#   trigger 2 : daily 09:20:06   (the auction / pre-open re-sample)
#   trigger 3 : daily 09:26:56   (the tail sample, same instant as the
#                                 HotPreopen3Min tail shot)
#   trigger 4 : at logon, single shot -> the same append also fires as soon
#               as the Administrator logs on, so a fresh append exists
#               without waiting for 09:00.
#   action    : wscript.exe run_hidden.vbs "<run_ld_top3_blk_551884.bat>"
#               -> SILENT. The task principal has to stay interactive, so
#                  a direct .bat action would pop a console window on the
#                  desktop on every trigger; wscript.exe with window style
#                  0 hides it (see run_hidden.vbs). run_hidden.vbs waits
#                  for the .bat to finish, so the Queue policy below still
#                  sees the task as running and nothing gets dropped.
#
# Why 55188.blk is shared with the older program
# ----------------------------------------------
# blocknew\55188.blk belongs to a_export_tdx_hot_rank.py
# (HotRankTDX_Intraday). That script rewrites the whole file only on its
# FIRST pass of the day - i.e. it clears the block once and lays down the
# day's baseline - and APPENDS on every later 10-min pass. This task also
# only appends, so both sides can write the same block without wiping each
# other: the 55188 block is the older program's union of the three 55188
# boards plus whatever top3 rows this task appends.
# (blocknew\551884.blk is no longer used; the launcher keeps its old name
# only so this registered task keeps pointing at the same file.)
#
#   principal : the logged-on Administrator, InteractiveToken (same as
#               HotPreopen3Min / HotRankTDX_Intraday).
#   policy    : Queue (a slow pass is never silently dropped), 10 min cap,
#               StartWhenAvailable.
#
# This task is ADDITIVE: it registers a new task and touches nothing else.
# It only READS _hot_archive\hot_trace.jsonl - it never fetches any board
# and never re-renders the table (that is HotRankTDX_Intraday/HotLdTimeline).
#
# Usage (PowerShell; registering a task may require an elevated window):
#   powershell -ExecutionPolicy Bypass -File .\register_ld_top3_blk_task.ps1
#   powershell -ExecutionPolicy Bypass -File .\register_ld_top3_blk_task.ps1 -Remove
#
# Manual run / inspect:
#   Start-ScheduledTask  -TaskName HotLdTop3Blk
#   Get-ScheduledTask    -TaskName HotLdTop3Blk | Get-ScheduledTaskInfo

param([switch]$Remove)

$ErrorActionPreference = "Stop"

$TaskName = "HotLdTop3Blk"
$Dir = $PSScriptRoot
$Bat = Join-Path $Dir "run_ld_top3_blk_551884.bat"
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

# --- the three fixed slots -------------------------------------------------
$t1 = New-ScheduledTaskTrigger -Daily -At "09:00:09"
$t2 = New-ScheduledTaskTrigger -Daily -At "09:20:06"
$t3 = New-ScheduledTaskTrigger -Daily -At "09:26:56"

# --- plus one run at logon -------------------------------------------------
$logon = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet -MultipleInstances Queue `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd

$principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" `
        -LogonType Interactive

Register-ScheduledTask -TaskName $TaskName -Action $action `
        -Trigger @($t1, $t2, $t3, $logon) -Settings $settings -Principal $principal `
        -Description "Program 2: append the 3 codes shown as the last row of the 55188 ld change-points table into blocknew\55188.blk at 09:00:09 / 09:20:06 / 09:26:56 and once at logon (read-only on the trace; append-only, shares 55188.blk with a_export_tdx_hot_rank.py which clears it once per day then also appends)" `
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
