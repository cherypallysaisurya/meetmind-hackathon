#!/bin/sh
# Start the whole local stack: DynamoDB Local, Ollama, the MeetMind service, the desktop app.
# Run from anywhere: scripts/start_local.sh
set -e
cd "$(dirname "$0")/.."

echo "1/4 DynamoDB Local (Docker)"
docker compose up -d
export $(grep -E "^DYNAMODB_ENDPOINT=" .env)   # create_tables.py reads it from the environment
backend/.venv/bin/python scripts/create_tables.py > /dev/null

echo "2/4 Ollama"
if ! curl -s http://127.0.0.1:11434/api/version > /dev/null; then
  brew services start ollama
  sleep 2
fi

echo "3/4 MeetMind service on 127.0.0.1:8080 (log: data/service.log)"
mkdir -p data
if curl -s http://127.0.0.1:8080/api/health > /dev/null; then
  echo "    already running"
else
  (cd backend && nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 > ../data/service.log 2>&1 & echo $! > ../data/service.pid)
  for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 1
    curl -s http://127.0.0.1:8080/api/health > /dev/null && break
  done
  curl -s http://127.0.0.1:8080/api/health > /dev/null || { echo "    the service did not come up, see data/service.log"; exit 1; }
fi
echo "    models are warming up in the background (about 5 s when loaded, longer after a reboot)"

echo "4/4 Desktop app"
cd desktop && npm run start --silent
