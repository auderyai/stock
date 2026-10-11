Option Explicit
Dim fso, shell, base, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
cmd = """" & fso.BuildPath(base, "..\.venv_krx_menu\Scripts\pythonw.exe") & """" _
      & " " & """" & fso.BuildPath(base, "scripts\run_krx_menu.py") & """"
shell.CurrentDirectory = fso.GetParentFolderName(base)
shell.Run cmd, 0, False
