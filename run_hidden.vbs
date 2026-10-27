' ===========================================================
'  run_hidden.vbs - launch a launcher .bat with NO console window.
'
'  Wired into the three interactive tasks (HotRankTDX_Intraday,
'  HotPreopen3Min, HotLdTop3Blk) as:
'      wscript.exe  <this file>  "<full path to the .bat>"
'
'  Why this exists
'  ---------------
'  Those tasks must keep LogonType=InteractiveToken, because the JYGS
'  leg of the chain needs a real desktop for its Playwright/OCR pass
'  (see the principal note in register_hot_preopen_task.ps1). But an
'  interactive task shows a console window on the desktop every single
'  time it fires - and with the all-day 10 min cadence of
'  HotRankTDX_Intraday that meant a cmd window popping up again and
'  again. wscript.exe is a GUI host, so it allocates no console of its
'  own, and window style 0 hides the console cmd.exe creates for the
'  .bat. The logon token stays interactive, so the desktop the JYGS
'  pass needs is still there.
'
'  Window style : 0 = hidden (1 normal, 3 maximised)
'  Wait         : True = block until the .bat has finished. This
'                 matters: Task Scheduler only sees the task as
'                 running while this process lives, and that is what
'                 keeps MultipleInstancesPolicy=Queue working (a slow
'                 pass is queued behind, never silently dropped).
'                 With False the task would look finished the instant
'                 the .bat started and two passes could overlap.
'  Exit code    : passed straight through from the .bat, so
'                 LastTaskResult still reports the chain's real result.
'
'  Usage  : wscript.exe run_hidden.vbs "C:\path\to\launcher.bat"
'  Manual : wscript.exe run_hidden.vbs ".\run_hot_rank_daily.bat"
'  NOTE   : keep this file ASCII-only (wscript/cscript read a .vbs with
'           the ANSI codepage unless it carries a UTF-16 BOM)
' ===========================================================
Option Explicit

Dim shell, batCmd, rc

If WScript.Arguments.Count = 0 Then
    WScript.Echo "usage: wscript.exe run_hidden.vbs ""<full path to .bat>"""
    WScript.Quit 2
End If

' quote the path so the spaces (and the non-ASCII folder name) survive
batCmd = """" & WScript.Arguments(0) & """"

Set shell = CreateObject("WScript.Shell")
rc = shell.Run(batCmd, 0, True)

WScript.Quit rc
