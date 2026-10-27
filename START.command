#!/bin/sh
# macOS Finder/Terminal entry point. Keep paths with spaces intact.
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1
PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PATH
if [ -x .venv/bin/python ]; then
    .venv/bin/python run.py --restart "$@"
    launch_result=$?
else
    launch_python=""
    for candidate in python3.13 python3.12 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert (3,12) <= sys.version_info[:2] < (3,14)' >/dev/null 2>&1; then
            launch_python="$candidate"
            break
        fi
    done
    if [ -z "$launch_python" ]; then
        echo 'Install Python 3.12 or 3.13 and Node.js 22.12+ or 24 LTS, then reopen START.command.'
        launch_result=1
    else
        "$launch_python" run.py --restart "$@"
        launch_result=$?
    fi
fi
if [ "$launch_result" -ne 0 ] && [ -t 0 ]; then
    printf '\nStartup failed. Read the error above. Press Enter to close. '
    read -r ignored
fi
exit "$launch_result"
