@echo off
title DNV System — Backup
color 0A

echo.
echo  Creating backup...
echo.

python -c "
import zipfile, os, sys
from pathlib import Path
from datetime import datetime

PROJECT    = Path(r'C:\Users\lchas\DNV _System')
BACKUP_DIR = Path(r'C:\Users\lchas\OneDrive\Documents\DNV Backups')
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

stamp    = datetime.now().strftime('%%Y-%%m-%%d_%%H%%M')
zip_name = BACKUP_DIR / f'dnv_system_{stamp}.zip'

INCLUDE_EXTS = {'.py','.html','.js','.css','.csv','.json','.txt','.bat','.md','.db','.docx','.xlsx'}
SKIP_DIRS    = {'__pycache__','.git','node_modules','venv','.venv','uploads','outputs','_backups'}

count = 0
with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(PROJECT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for file in files:
            fp = Path(root) / file
            if fp.suffix.lower() in INCLUDE_EXTS:
                zf.write(fp, fp.relative_to(PROJECT))
                count += 1

size_kb = zip_name.stat().st_size // 1024
print(f'  Saved: {zip_name.name}')
print(f'  Files: {count}  |  Size: {size_kb} KB')
"

echo.
echo  Location: C:\Users\lchas\OneDrive\Documents\DNV Backups\
echo  OneDrive will sync it automatically.
echo.
pause
