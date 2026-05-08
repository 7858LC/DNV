@echo off
title DNV Coordinator - Weekly Pipeline
color 0E

echo.
echo  ============================================================
echo   DNV BASTION COORDINATOR - Weekly Pipeline Run
echo  ============================================================
echo.
echo  Running Agents 1-5 (weekly mode)...
echo.

python orchestrator.py --mode weekly

echo.
echo  Pipeline complete. Check outputs\ for weekly_report.md
echo  Run start.bat to launch the dashboard.
echo.
pause