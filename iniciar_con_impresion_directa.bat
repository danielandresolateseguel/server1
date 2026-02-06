@echo off
echo Buscando Google Chrome...

if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe"
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
) else (
    echo No se encontro Chrome en las rutas estandar. Intentando abrir con comando default...
    set "CHROME_PATH=chrome.exe"
)

echo Iniciando KDS con Impresion Silenciosa...
echo Asegurate de que la impresora termica sea la PREDETERMINADA en Windows.
echo.

start "" "%CHROME_PATH%" --kiosk-printing "http://localhost:5000/admin"

exit
