#!/bin/bash
# Keep one planner process running on the IIT container (run inside tmux):
#   tmux new-session -d -s pond-app "bash ~/ai-village-pond-planning/scripts/run_server.sh"
# Internal port 3000 is published as external port 3233 for SSH port 2233.
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
export POND_HOST="${POND_HOST:-0.0.0.0}" POND_PORT="${POND_PORT:-3000}" POND_CACHE_DIR="${POND_CACHE_DIR:-$PWD/cache}"
while true; do
  echo "$(date -Is) starting planner on $POND_HOST:$POND_PORT" >> logs/app.log
  .venv/bin/python run.py >> logs/app.log 2>&1
  echo "$(date -Is) planner exited with status $?; restarting in 3 s" >> logs/app.log
  sleep 3
done
