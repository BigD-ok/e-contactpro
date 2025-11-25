@echo off
REM filepath: a:\profil_NFC\run.bat

REM Vérifier si l'environnement virtuel existe
if not exist "venv" (
    echo Creating virtual environment...
    py -m venv venv
)

REM Activer l'environnement virtuel
call venv\Scripts\activate.bat

REM Installer les dépendances
echo Installing requirements...
py -m pip install -r requirements.txt

REM Lancer l'app
echo Starting Flask app...
py app.py

pause