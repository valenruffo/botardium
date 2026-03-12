Set shell = CreateObject("WScript.Shell")
If WScript.Arguments.Count < 1 Then
  WScript.Quit 1
End If
cmd = WScript.Arguments(0)
shell.Run cmd, 0, False
