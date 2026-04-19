"""Shared test setup: isolated temp DB per test module."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    """Every test gets a fresh DB + tmp data dir and a fake .env."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_WHITELIST", "111")
    monkeypatch.setenv("INITIAL_CAPITAL_VND", "100000000")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    # reset cached settings + singletons
    import vnstock_bot.config as cfg
    cfg._settings = None
    import vnstock_bot.db.connection as conn
    conn._conn = None

    from vnstock_bot.db.connection import init_db
    init_db()
    yield
    conn._conn = None
