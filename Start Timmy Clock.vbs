' Double-click to open Timmy Clock (no black terminal window).
' Prefers TimmyClock.exe in plugin\timeassist\; else scripts\start_timmy_clock.cmd.

Option Explicit
Dim sh, fso, kit, clockExe, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
kit = fso.GetParentFolderName(WScript.ScriptFullName)
clockExe = kit & "\plugin\timeassist\TimmyClock.exe"
If fso.FileExists(clockExe) Then
  sh.Run """" & clockExe & """", 1, False
Else
  cmd = """" & kit & "\scripts\start_timmy_clock.cmd"""
  sh.Run cmd, 0, False
End If
