Set WshShell = WScript.CreateObject("WScript.Shell")
strDesktop = WshShell.SpecialFolders("Desktop")
Set Shortcut = WshShell.CreateShortcut(strDesktop & "\Clawdbot Trader.lnk")
Shortcut.TargetPath = "C:\ai trader\AI-Trader\START_TRADER.bat"
Shortcut.WorkingDirectory = "C:\ai trader\AI-Trader"
Shortcut.IconLocation = "C:\Windows\System32\shell32.dll,23"
Shortcut.Save()
WScript.Echo "Desktop shortcut created!"
