#!/usr/bin/env bash
# wait-for-it.sh — wait for a host:port using Python socket (no nc required)
set -e

HOST="$1"
PORT="$2"
TIMEOUT="${3:-60}"

echo "Waiting for $HOST:$PORT (timeout=${TIMEOUT}s)..."

python3 - <<EOF
import socket, sys, time

host, port, timeout = "$HOST", int("$PORT"), int("$TIMEOUT")
start = time.time()
while True:
    try:
        s = socket.create_connection((host, port), timeout=2)
        s.close()
        print(f"{host}:{port} is available")
        sys.exit(0)
    except OSError:
        elapsed = int(time.time() - start)
        if elapsed >= timeout:
            print(f"Timeout waiting for {host}:{port}")
            sys.exit(1)
        print(f"  still waiting ({elapsed}/{timeout}s)...")
        time.sleep(1)
EOF
