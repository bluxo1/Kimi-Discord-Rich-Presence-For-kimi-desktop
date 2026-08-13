' Kimi Desktop -> Discord Rich Presence : silent background launcher.
'
' Runs the bridge with NO terminal window using the project's windowless
' Python (pythonw.exe). A shortcut to this file in the Windows Startup folder
' makes the presence start automatically at login -- no command, no terminal.
'
' It computes every path from its OWN location, so keep this file in the
' project root next to config.yaml. Moving the project is fine; a stale
' Startup shortcut is the only thing that would need re-pointing.

Option Explicit

Dim fso, shell, here, pythonw, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

' The folder this script lives in = the project root.
here = fso.GetParentFolderName(WScript.ScriptFullName)

' Prefer the project's virtualenv (windowless Python); fall back to a system one.
pythonw = fso.BuildPath(here, ".venv\Scripts\pythonw.exe")
If Not fso.FileExists(pythonw) Then
    pythonw = "pythonw.exe"
End If

' Run FROM the project dir so config.local.yaml / config.yaml are picked up.
shell.CurrentDirectory = here
cmd = """" & pythonw & """ -m kimi_discord_rpc"

' 0 = hidden window, False = do not wait for it to exit.
shell.Run cmd, 0, False
