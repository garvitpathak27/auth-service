"""Gunicorn configuration for Auth Service."""

import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("WEB_CONCURRENCY", "3"))
worker_class = "sync"
threads = 1
timeout = 30
graceful_timeout = 30
keepalive = 30
preload_app = False
max_requests = 0
accesslog = None
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

