@echo off
setlocal

for %%P in (3000 8000) do (
  for /f "tokens=5" %%I in ('netstat -ano ^| findstr LISTENING ^| findstr :%%P') do (
    taskkill /PID %%I /F >nul 2>&1
  )
)

echo Stack local detenido en puertos 3000 y 8000.

endlocal
