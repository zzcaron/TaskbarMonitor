' 静默启动脚本，完全无命令行弹窗
Set ws = CreateObject("Wscript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.Run """C:\Users\Administrator\AppData\Local\Programs\Python\Python312\pythonw.exe"" """ & currentDir & "\main.py""", 0, False
