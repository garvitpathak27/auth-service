#!/bin/sh
set -e

python3 manage.py migrate --noinput
python3 manage.py grpcrunserver --max-workers=10 0.0.0.0:50051 &
exec python3 manage.py runserver 0.0.0.0:8000