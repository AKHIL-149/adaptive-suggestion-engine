#!/bin/bash
# Launch the Adaptive Suggestion Engine desktop overlay
# Usage: bash run_desktop.sh  (from project root)

# Use Anaconda Python explicitly
PYTHON=/opt/anaconda3/bin/python3

# Find Qt platform plugins path from Anaconda's PyQt6
export QT_QPA_PLATFORM_PLUGIN_PATH="$($PYTHON -c "import PyQt6, os; print(os.path.join(os.path.dirname(PyQt6.__file__), 'Qt6/plugins/platforms'))")"

echo "[ASE] Qt plugin path: $QT_QPA_PLATFORM_PLUGIN_PATH"
echo "[ASE] Starting overlay..."

cd "$(dirname "$0")"
$PYTHON -m desktop.main
