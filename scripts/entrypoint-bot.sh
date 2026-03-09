#!/bin/sh

uv run playwright install-deps
uv run playwright install firefox

uv run --no-dev python run.py