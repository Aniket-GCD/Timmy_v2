@echo off
setlocal EnableExtensions
rem Fallback launcher when TimmyClock.exe is not in plugin\timeassist\.
rem Prefer: copy TimmyClock.exe next to .mcp.json and double-click that.

set "KIT=%~dp0.."
pushd "%KIT%" >nul 2>&1
if errorlevel 1 (
  echo Could not open the Timmy kit folder.
  pause
  exit /b 1
)
set "KIT=%CD%"
popd

if exist "%KIT%\plugin\timeassist\TimmyClock.exe" (
  start "" "%KIT%\plugin\timeassist\TimmyClock.exe"
  exit /b 0
)
if exist "%KIT%\dist\TimmyClock.exe" (
  start "" "%KIT%\dist\TimmyClock.exe"
  exit /b 0
)

set "DB="
if defined CLAUDE_PLUGIN_DATA if exist "%CLAUDE_PLUGIN_DATA%\timeassist.sqlite" (
  set "DB=%CLAUDE_PLUGIN_DATA%\timeassist.sqlite"
)
if not defined DB if exist "%KIT%\timeassist.sqlite" set "DB=%KIT%\timeassist.sqlite"
if not defined DB (
  for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$roots=@($env:LOCALAPPDATA,$env:APPDATA); $hit=$null; foreach($r in $roots){ if(-not $r){continue}; $hit=Get-ChildItem -LiteralPath $r -Filter timeassist.sqlite -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if($hit){ break } }; if($hit){ $hit.FullName }"`) do set "DB=%%I"
)
if not defined DB (
  powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Could not find Timmy''s database (timeassist.sqlite).`n`n1. Open Claude and use Timmy once`n2. Then try again.`n`nOr copy TimmyClock.exe into your Timmy folder (next to .mcp.json).','Timmy Clock',0,'Error') | Out-Null"
  exit /b 1
)

set "EXE="
if exist "%KIT%\plugin\timeassist\bin\timeassist.exe" set "EXE=%KIT%\plugin\timeassist\bin\timeassist.exe"
if not defined EXE if exist "%KIT%\plugin\timeassist\engine\timeassist.exe" set "EXE=%KIT%\plugin\timeassist\engine\timeassist.exe"
if not defined EXE if exist "%KIT%\dist\timeassist.exe" set "EXE=%KIT%\dist\timeassist.exe"
if not defined EXE if exist "%KIT%\bin\timeassist.exe" set "EXE=%KIT%\bin\timeassist.exe"

if defined EXE (
  "%EXE%" --db "%DB%" tray
  exit /b %ERRORLEVEL%
)

where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%KIT%\scripts\timeassist.py" --db "%DB%" tray
  exit /b %ERRORLEVEL%
)
where python >nul 2>&1
if not errorlevel 1 (
  python "%KIT%\scripts\timeassist.py" --db "%DB%" tray
  exit /b %ERRORLEVEL%
)

powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Build or copy TimmyClock.exe into plugin\timeassist (next to .mcp.json), or install Python / timeassist.exe.','Timmy Clock',0,'Error') | Out-Null"
exit /b 1
