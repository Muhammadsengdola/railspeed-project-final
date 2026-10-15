@echo off
REM RailSpeed: first run creates a virtual environment, installs Django, builds the database with demo data
cd /d %~dp0
set PYTHONUTF8=1
if not exist .venv (
  python -m venv .venv
  call .venv\Scripts\activate
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate
)
python manage.py migrate
if not exist db_seeded.flag (
  python manage.py seed --reset && echo seeded> db_seeded.flag
)
python manage.py runserver
