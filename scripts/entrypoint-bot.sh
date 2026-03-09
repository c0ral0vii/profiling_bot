#!/bin/sh

uv run playwright install-deps
uv run playwright install

uv run --no-dev python run.py