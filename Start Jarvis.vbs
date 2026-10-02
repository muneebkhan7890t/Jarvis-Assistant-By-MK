Option Explicit
Dim shell, files, folder, python, console, candidate, status
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
python = ""
For Each candidate In Array(".venv-liv", ".venv")
  console = folder & "\" & candidate & "\Scripts\python.exe"
  If files.FileExists(console) Then
    status = shell.Run(Chr(34) & console & Chr(34) & " -c " & Chr(34) & "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" & Chr(34), 0, True)
    If status = 0 Then
      python = folder & "\" & candidate & "\Scripts\pythonw.exe"
      Exit For
    End If
  End If
Next
If python = "" Then
  MsgBox "No usable project Python environment was found. Please run Setup Windows.cmd. Your old environment has not been deleted.", 48, "MARK LIV"
  WScript.Quit 1
End If
shell.CurrentDirectory = folder
shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & folder & "\launch.py" & Chr(34), 0, False
