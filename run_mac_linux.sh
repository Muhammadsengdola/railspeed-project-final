#!/usr/bin/env bash
# RailSpeed: first run creates a virtual environment, installs Django, builds the database with demo data
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
else
  source .venv/bin/activate
fi
python manage.py migrate
if [ ! -f db_seeded.flag ]; then python manage.py seed --reset && echo seeded > db_seeded.flag; fi
python manage.py runserver
