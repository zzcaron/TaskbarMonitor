' 静默启动脚本（无命令行弹窗，自动适配打包 exe、虚拟环境与系统 Python）
Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)

exeSingle = currentDir & "\dist\TaskbarMonitor.exe"
exeDir = currentDir & "\dist\TaskbarMonitor\TaskbarMonitor.exe"
venvPyw = currentDir & "\.venv\Scripts\pythonw.exe"
mainPy = currentDir & "\main.py"

If fso.FileExists(exeSingle) Then
    ws.Run """" & exeSingle & """", 0, False
ElseIf fso.FileExists(exeDir) Then
    ws.Run """" & exeDir & """", 0, False
ElseIf fso.FileExists(venvPyw) Then
    ws.Run """" & venvPyw & """ """ & mainPy & """", 0, False
Else
    On Error Resume Next
    ws.Run "pythonw """ & mainPy & """", 0, False
    If Err.Number <> 0 Then
        Err.Clear
        ws.Run "pyw """ & mainPy & """", 0, False
    End If
    On Error GoTo 0
End If
