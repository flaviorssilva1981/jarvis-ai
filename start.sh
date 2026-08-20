#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate

mkdir -p logs

# Scale entire UI (text, buttons, panels). 1.0 = default, 1.5 = 50% larger, 2.0 = double.
SCALE=$(python -c "
import json
from pathlib import Path
try:
    cfg = json.loads(Path('config/api_keys.json').read_text())
    print(float(cfg.get('ui_font_scale', 1.5)))
except Exception:
    print(1.5)
")
export QT_SCALE_FACTOR="${SCALE}"

# Stream to terminal AND logs/jarvis.log (watch: tail -f logs/jarvis.log)
python main.py 2>&1 | tee -a logs/jarvis.log
