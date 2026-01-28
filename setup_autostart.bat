@echo off
echo Setting up JRPD service to start automatically...
echo.
echo Creating startup entry for JRPD service...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "JRPDService" /t REG_SZ /d "D:\rpd\label_marks_complete_service.py" /f
echo.
echo NOTE: Due to Windows security restrictions, you may need to run this with admin privileges
echo or manually add the Python script to your startup folder.
echo.
echo Alternatively, you can:
echo 1. Press Win+R, type "shell:startup" and press Enter
echo 2. Create a shortcut to "python D:\rpd\label_marks_complete_service.py"
echo 3. Place the shortcut in the opened folder
echo.
pause