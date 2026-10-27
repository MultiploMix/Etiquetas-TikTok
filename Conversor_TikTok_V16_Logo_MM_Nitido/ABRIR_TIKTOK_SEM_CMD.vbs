Option Explicit
Dim sh, fso, pasta, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
pasta = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = pasta
cmd = "pyw " & Chr(34) & fso.BuildPath(pasta, "ABRIR_TIKTOK.pyw") & Chr(34)
sh.Run cmd, 0, False
