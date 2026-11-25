@echo off
REM Arranca el gemelo climatico de Tenerife (servidor local + visor en el navegador)
cd /d "%~dp0"
if not exist config.ini (
  copy config.ini.ejemplo config.ini >nul
  echo Se ha creado config.ini. Edita la API key de AEMET y vuelve a ejecutar.
  notepad config.ini
)
python gemelo.py %*
pause
