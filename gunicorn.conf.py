#!/usr/bin/env python3
"""
gunicorn.conf.py — Production Gunicorn config for zrouter-web.

Usage:
    gunicorn -c gunicorn.conf.py web_app:app
"""

import os

# --------------------------------------------------------------------------- #
# Socket
# --------------------------------------------------------------------------- #
bind = os.environ.get("WEB_BIND", "0.0.0.0:8000")
backlog = 2048

# --------------------------------------------------------------------------- #
# Worker processes
# --------------------------------------------------------------------------- #
workers = int(os.environ.get("WEB_WORKERS", "4"))
worker_class = "gthread"
threads = int(os.environ.get("WEB_THREADS", "8"))
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 100
timeout = 120
graceful_timeout = 30
keepalive = 5

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("WEB_LOG_LEVEL", "info")
access_log_format = "%(h)s %(r)s %(s)s %(b)s %(D)sµs"

# --------------------------------------------------------------------------- #
# Process naming
# --------------------------------------------------------------------------- #
proc_name = "zrouter-web"


# --------------------------------------------------------------------------- #
# Server hooks
# --------------------------------------------------------------------------- #
def on_starting(server):
    server.log.info("zrouter-web starting (workers=%d, threads=%d)", workers, threads)


def on_exit(server):
    server.log.info("zrouter-web shutting down")
