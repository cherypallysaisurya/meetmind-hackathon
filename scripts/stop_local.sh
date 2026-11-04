#!/bin/sh
# Stop the MeetMind service and DynamoDB Local. Ollama keeps running (it is a brew service); the desktop app is closed by hand.
cd "$(dirname "$0")/.."
if [ -f data/service.pid ]; then
  kill "$(cat data/service.pid)" 2>/dev/null && echo "service stopped" || echo "service was not running"
  rm -f data/service.pid
fi
docker compose down
