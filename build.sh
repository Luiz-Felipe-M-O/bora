#!/usr/bin/env bash
# Termina a execução se ocorrer algum erro
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate