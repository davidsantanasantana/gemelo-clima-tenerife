@echo off
REM Registra en el Programador de tareas de Windows la descarga HORARIA y la consolidacion DIARIA,
REM para que el historico crezca aunque el visor (gemelo.py) no este abierto.
REM Ejecutar una vez. Para quitarlas:  schtasks /Delete /TN "GemeloTenerife\Actualizar" /F  (idem Consolidar)
cd /d "%~dp0"
for /f "delims=" %%i in ('where python') do (set "PY=%%i" & goto :encontrado)
echo No se encuentra python en el PATH. & pause & exit /b 1
:encontrado
schtasks /Create /TN "GemeloTenerife\Actualizar" /TR "\"%PY%\" \"%~dp0colector.py\" actualizar" /SC HOURLY /ST 00:40 /F
schtasks /Create /TN "GemeloTenerife\Consolidar" /TR "\"%PY%\" \"%~dp0colector.py\" consolidar" /SC DAILY /ST 00:50 /F
echo.
echo Tareas creadas. Si las usas, puedes poner  interno = no  en [programador] de config.ini
echo (si lo dejas en "si" no pasa nada: los datos se deduplican).
pause
