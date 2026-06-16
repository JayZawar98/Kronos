#!/usr/bin/env bash
# Quick start script for the Kronos Live Dashboard

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Waiting for it to be created..."
    exit 1
fi

echo "Starting Kronos Dashboard..."
.venv/bin/python dashboard.py
