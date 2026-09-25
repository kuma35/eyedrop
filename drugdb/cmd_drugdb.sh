#!/bin/sh
# 目薬管理コマンドライン版。 どこから実行してもよい
PYTHONPATH="$(cd "$(dirname "$0")/.." && pwd)${PYTHONPATH:+:$PYTHONPATH}" \
    exec python3 -m drugdb "$@"
