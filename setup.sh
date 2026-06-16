#!/bin/bash
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip
cd /home/ubuntu/Kronos
python3 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt
.venv/bin/pip install --no-cache-dir flask flask-cors plotly ccxt fyers-apiv3 fyers-model python-dotenv
echo "Setup Complete!"
