"""
Base de datos SQLite para almacenar excursiones.
"""
import os
import sqlite3
from datetime import date, datetime
from typing import Optional

# En Railway, montar un volumen en /data y definir DB_PATH=/data/excursions.db
# para que los datos sobrevivan a cada redeploy.
DB_PATH = os.environ.get('DB_PATH', 'excursions.db')
_db_dir = os.path.dirname(DB_PATH)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)


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
                cancelled            INTEGER DEFAULT 0,
                calendar_event_id    TEXT,
                created_at           TEXT DEFAULT (datetime('now'))
            )
        ''')
        # Migraciones para DBs existentes
        for col, definition in [
            ('cancelled', 'INTEGER DEFAULT 0'),
            ('calendar_event_id', 'TEXT'),
            ('planilla_custom', 'TEXT'),
            ('item_edits', 'TEXT'),
            ('extras', 'TEXT'),
            ('agency', 'TEXT'),
            ('driver', 'TEXT'),
            ('wetsuit', 'TEXT'),
            ('personal', 'INTEGER'),
        ]:
            try:
                conn.execute(f'ALTER TABLE excursions ADD COLUMN {col} {definition}')
            except Exception:
                pass
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
                 gastronomy_type, dietary_restrictions, hora, planilla_path, calendar_event_id, extras,
                 agency, driver, wetsuit, personal)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            data.get('calendar_event_id'),
            ','.join(data.get('extras') or []) if isinstance(data.get('extras'), (list, tuple)) else data.get('extras'),
            data.get('agency'), data.get('driver'), data.get('wetsuit'), data.get('personal'),
        ))
        return cur.lastrowid


def get_excursions_for_date(target_date: date) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM excursions WHERE date = ? AND (cancelled IS NULL OR cancelled=0) ORDER BY hora',
            (target_date.isoformat(),)
        ).fetchall()
    return [dict(r) for r in rows]


def find_excursions(target_date: date, identifier: str = None, identifier_type: str = None) -> list:
    """Busca excursiones por fecha y opcionalmente por guía o cliente."""
    with get_conn() as conn:
        if identifier and identifier_type == 'guide':
            rows = conn.execute(
                'SELECT * FROM excursions WHERE date=? AND guide LIKE ? AND (cancelled IS NULL OR cancelled=0)',
                (target_date.isoformat(), f'%{identifier}%')
            ).fetchall()
        elif identifier and identifier_type == 'client':
            # Busca por cliente Y por guía (por si el nombre es del guía)
            rows = conn.execute(
                '''SELECT * FROM excursions WHERE date=?
                   AND (client LIKE ? OR guide LIKE ?)
                   AND (cancelled IS NULL OR cancelled=0)''',
                (target_date.isoformat(), f'%{identifier}%', f'%{identifier}%')
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM excursions WHERE date=? AND (cancelled IS NULL OR cancelled=0)',
                (target_date.isoformat(),)
            ).fetchall()
    return [dict(r) for r in rows]


def update_excursion(exc_id: int, field: str, value) -> bool:
    """Actualiza un campo de una excursión. Devuelve True si actualizó."""
    allowed = {'hora', 'guide', 'date', 'dietary_restrictions', 'pax', 'site', 'hotel', 'client', 'extras',
               'agency', 'driver', 'wetsuit', 'personal'}
    if field not in allowed:
        return False
    val = value.isoformat() if hasattr(value, 'isoformat') else value
    with get_conn() as conn:
        conn.execute(f'UPDATE excursions SET {field}=? WHERE id=?', (val, exc_id))
    return True


def append_restrictions(exc_id: int, new_restrictions: str) -> str:
    """Agrega restricciones a las existentes. Devuelve el valor final."""
    with get_conn() as conn:
        row = conn.execute('SELECT dietary_restrictions FROM excursions WHERE id=?', (exc_id,)).fetchone()
        existing = row['dietary_restrictions'] if row and row['dietary_restrictions'] else ''
        combined = ', '.join(filter(None, [existing, new_restrictions]))
        conn.execute('UPDATE excursions SET dietary_restrictions=? WHERE id=?', (combined, exc_id))
    return combined


def cancel_excursion(exc_id: int) -> bool:
    """Marca una excursión como cancelada (queda en la base como historial,
    pero ya no aparece en consultas, avisos ni resúmenes)."""
    with get_conn() as conn:
        conn.execute('UPDATE excursions SET cancelled=1 WHERE id=?', (exc_id,))
    return True


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


def get_upcoming(days: int = 14) -> list:
    """Salidas activas desde hoy hasta dentro de `days` días."""
    from datetime import timedelta
    today = date.today()
    with get_conn() as conn:
        rows = conn.execute(
            '''SELECT * FROM excursions WHERE date >= ? AND date <= ?
               AND (cancelled IS NULL OR cancelled=0) ORDER BY date, hora''',
            (today.isoformat(), (today + timedelta(days=days)).isoformat())
        ).fetchall()
    return [dict(r) for r in rows]


def _month_key(name: str) -> str:
    return f"counter_{name}_{date.today().strftime('%Y-%m')}"


def incr_counter(name: str):
    key = _month_key(name)
    save_setting(key, str(int(get_setting(key) or 0) + 1))


def get_counter(name: str) -> int:
    return int(get_setting(_month_key(name)) or 0)


def get_excursion(exc_id: int):
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM excursions WHERE id=?', (exc_id,)).fetchone()
    return dict(row) if row else None


def set_custom_planilla(exc_id: int, path):
    with get_conn() as conn:
        conn.execute('UPDATE excursions SET planilla_custom=? WHERE id=?', (path, exc_id))


def known_guides() -> list:
    """Nombres de guías ya usados (para reconocer "con Rodri")."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT guide FROM excursions WHERE guide IS NOT NULL AND guide != ''"
        ).fetchall()
    return [r['guide'] for r in rows]


def get_item_edits(exc_id: int) -> list:
    import json
    row = get_excursion(exc_id)
    try:
        return json.loads(row['item_edits']) if row and row.get('item_edits') else []
    except ValueError:
        return []


def add_item_edit(exc_id: int, edit: dict):
    """Guarda un cambio de ítem (se aplican en orden cada vez que se arma la planilla)."""
    import json
    edits = get_item_edits(exc_id) + [edit]
    with get_conn() as conn:
        conn.execute('UPDATE excursions SET item_edits=? WHERE id=?', (json.dumps(edits, ensure_ascii=False), exc_id))


def clear_item_edits(exc_id: int):
    with get_conn() as conn:
        conn.execute('UPDATE excursions SET item_edits=NULL WHERE id=?', (exc_id,))
