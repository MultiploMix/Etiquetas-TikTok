@echo off
cd /d "%~dp0"
echo CONVERSOR TIKTOK - DIAGNOSTICO
py -0p
py -m pip install pymupdf "qrcode[pil]"
if errorlevel 1 (
 echo Falha ao instalar bibliotecas.
 pause
 exit /b 1
)
py ABRIR_TIKTOK.pyw
echo Se nao abriu, verifique ERRO_INICIALIZACAO.txt.
pause
