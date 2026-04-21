#!/bin/bash
# Launch the desktop overlay
# Run from project root: bash run_desktop.sh

export QT_QPA_PLATFORM_PLUGIN_PATH="$(python3 -c "import PyQt6, os; print(os.path.join(os.path.dirname(PyQt6.__file__), 'Qt6/plugins/platforms'))")"

cd "$(dirname "$0")"
python3 -m desktop.main
