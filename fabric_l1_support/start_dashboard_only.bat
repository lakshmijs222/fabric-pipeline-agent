@echo off
title Fabric L1 Dashboard

cd /d D:\Claude\fabric-l1-bot\fabric_l1_support

echo Starting Fabric L1 Dashboard...
start http://localhost:8503
streamlit run dashboard/app.py --server.port 8503

pause
