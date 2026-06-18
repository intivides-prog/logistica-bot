"""
Base de datos SQLite para almacenar excursiones.
"""
import sqlite3
from datetime import date, datetime
from typing import Optional

DB_PATH = 'excursions.db'


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS excursions (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                date                 TEXT NOT NULL,
                activity             TEXT,
                site                 TEXT,
                pax                  INTEGER,
                guide                TEXT,
                hotel                TEXT,
                client               TEXT,
                gastronomy_type      TEXT,
                dietary_restrictions TEXT,
                hora                 TEXT,
                planilla_path        TEXT,
                created_at           TEXT DEFAULT (datetime('now'))
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        ''')


def save_excursion(data: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute('''
            INSERT INTO excursions
                (date, activity, site, pax, guide, hotel, client,
                 gastronomy_type, dietary_restrictions, hora, planilla_path)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            data.get('date').isoformat() if data.get('date') else None,
            data.get('activity'),
            data.get('site'),
            data.get('pax'),
            data.get('guide'),
            data.get('hotel'),
            data.get('client'),
            data.get('gastronomy_type', 'AC'),
            data.get('dietary_restrictions'),
            data.get('hora'),
            data.get('planilla_path'),
        ))
        return cur.lastrowid


def get_excursions_for_date(target_date: date) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM excursions WHERE date = ? ORDER BY hora',
            (target_date.isoformat(),)
        ).fetchall()
    return [dict(r) for r in rows]


def save_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)',
            (key, value)
        )


def get_setting(key: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            'SELECT value FROM settings WHERE key=?', (key,)
        ).fetchone()
    return row['value'] if row else None
