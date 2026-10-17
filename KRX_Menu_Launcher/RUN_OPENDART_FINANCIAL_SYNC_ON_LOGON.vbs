Option Explicit
Dim shell
Set shell = CreateObject("WScript.Shell")
shell.Run """C:\stock\KRX_Menu_Launcher\sync_opendart_financial_from_drive.cmd""", 0, False
