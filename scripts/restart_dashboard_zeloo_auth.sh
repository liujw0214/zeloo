#!/usr/bin/env bash
set -e
cd /root/zeloo
export ZELOO_DASHBOARD_BASIC_AUTH_USERNAME='zeloo'
export ZELOO_DASHBOARD_BASIC_AUTH_PASSWORD='zeloo'
export ZELOO_DASHBOARD_BASIC_AUTH_SECRET='zeloo-static-secret-2026'
exec setsid nohup .venv/bin/python -m zeloo_cli.main dashboard \
  --host 0.0.0.0 --port 9119 --no-open --skip-build \
  > /tmp/dash.log 2>&1 < /dev/null