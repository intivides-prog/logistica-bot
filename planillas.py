"""
Manejo de planillas: generadas por el bot o editadas a mano.

Si alguien edita una planilla en Excel y se la manda al bot, se guarda como
"versión editada" de esa salida. Desde ahí:
  - los reenvíos mandan esa versión;
  - las modificaciones (hora, pax, guía…) actualizan solo la cabecera
    (filas 2 a 12) y respetan todo lo que se haya cambiado a mano abajo.
"""
import os
import shutil
from datetime import date

from openpyxl import load_workbook
import re
import unicodedata

import db
import generator

CUSTOM_DIR = os.path.join(os.path.dirname(db.DB_PATH) or '.', 'planillas_editadas')

# Celdas de la cabecera (ver generator._cabecera)
HEADER_CELLS = {
    'activity': 'B2', 'site': 'B3', 'date': 'B4', 'hora': 'B5', 'pax': 'B6',
    'client': 'B7', 'hotel': 'B9', 'guide': 'B10', 'dietary_restrictions': 'B12',
}


def _as_date(val):
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val)[:10])
    except (TypeError, ValueError):
        return None


# ── Cambios de ítems pedidos por chat ─────────────────────────────────────────

def _norm(text) -> str:
    t = unicodedata.normalize('NFD', str(text or '').lower())
    return ''.join(c for c in t if unicodedata.category(c) != 'Mn')


def _stem(word: str) -> str:
    for suf in ('es', 's'):
        if len(word) > 4 and word.endswith(suf):
            return word[:-len(suf)]
    return word


def _matches(item: str, label: str) -> bool:
    """¿El ítem pedido ("vinos") corresponde a esta fila ("Vinos (botellas)")?"""
    label_words = re.findall(r'[a-z0-9]+', _norm(label))
    item_words = [w for w in re.findall(r'[a-z0-9]+', _norm(item)) if w not in ('de', 'del', 'la', 'el', 'para')]
    if not item_words:
        return False
    return all(any(lw.startswith(_stem(iw)) or _stem(lw) == _stem(iw) for lw in label_words) for iw in item_words)


def _item_rows(ws):
    """Filas de ítems (debajo de la cabecera, salteando títulos de sección y encabezados)."""
    for r in range(14, ws.max_row + 1):
        a = ws[f"A{r}"].value
        if not a or str(a).startswith('  ') or a == 'Item':
            continue
        yield r, str(a)


def _qty_value(qty):
    if qty is None:
        return None
    q = str(qty).replace(',', '.')
    try:
        f = float(q)
        return int(f) if f.is_integer() else f
    except ValueError:
        return qty


def apply_item_edits(ws, edits: list) -> list[str]:
    """Aplica los cambios a la hoja. Devuelve un resumen legible de cada cambio."""
    from generator import _sec, _hdr, _it, _gap
    report = []
    extra_start = None
    for e in edits:
        op, item, qty = e.get('op'), e.get('item', ''), _qty_value(e.get('qty'))
        row = next((r for r, label in _item_rows(ws) if _matches(item, label)), None)
        if row:
            label = ws[f"A{row}"].value
            cur = ws[f"B{row}"].value
            if op == 'remove':
                ws[f"B{row}"].value = '/'
                report.append(f"{label} → quitado")
            elif op == 'add':
                if isinstance(cur, str) and cur.startswith('='):
                    ws[f"B{row}"].value = f"=({cur[1:]})+{qty}"
                elif isinstance(cur, (int, float)) or (isinstance(cur, str) and cur.strip().isdigit()):
                    ws[f"B{row}"].value = int(cur) + int(qty) if str(qty).isdigit() else qty
                else:
                    ws[f"B{row}"].value = qty
                report.append(f"{label} → +{qty}")
            else:
                ws[f"B{row}"].value = qty
                report.append(f"{label} → {qty}")
            if not ws[f"C{row}"].value:
                ws[f"C{row}"].value = 'cambiado por chat'
            continue
        if op == 'remove':
            report.append(f"No encontré «{item}» en la planilla")
            continue
        # Ítem nuevo: va a la sección AGREGADOS al final
        if extra_start is None:
            extra_start = ws.max_row + 2
            _gap(ws, extra_start - 1)
            _sec(ws, extra_start, "  AGREGADOS")
            _hdr(ws, extra_start + 1)
        r = ws.max_row + 1
        _it(ws, r, item.capitalize(), qty, mode="input")
        report.append(f"{item.capitalize()} (nuevo) → {qty}")
    return report


def build_file(row: dict, output_dir: str) -> tuple[str, bool]:
    """
    Arma el archivo de la planilla para una salida guardada.
    Devuelve (ruta, es_editada_a_mano).
    """
    params = {**row, 'date': _as_date(row.get('date'))}
    custom = row.get('planilla_custom')
    if custom and os.path.exists(custom):
        filename = os.path.basename(generator.generate(params, output_dir=output_dir))
        out = os.path.join(output_dir, filename.replace('.xlsx', '_editada.xlsx'))
        wb = load_workbook(custom)
        ws = wb.worksheets[0]
        for field, cell in HEADER_CELLS.items():
            val = params.get(field)
            if field == 'date':
                val = val.strftime('%d/%m/%Y') if val else ws[cell].value
            elif field == 'dietary_restrictions':
                val = val or 'Ninguna'
            elif field == 'activity':
                val = ws[cell].value or val     # respeta el nombre que pusieron a mano
            if val not in (None, ''):
                ws[cell].value = val
        # Extras pedidos después de editar a mano: se agregan al final si no están
        titles = {str(ws[f"A{r}"].value or '').strip() for r in range(1, ws.max_row + 1)}
        faltan = [e for e in generator.parse_extras(row.get('extras'))
                  if generator.EXTRAS[e][0] not in titles]
        if faltan:
            generator.add_extras_sections(ws, ws.max_row + 2, faltan)
        apply_item_edits(ws, db.get_item_edits(row['id']))
        wb.calculation.fullCalcOnLoad = True    # Excel recalcula las fórmulas al abrir
        wb.save(out)
        return out, True
    path = generator.generate(params, output_dir=output_dir)
    edits = db.get_item_edits(row['id']) if row.get('id') else []
    if edits:
        wb = load_workbook(path)
        apply_item_edits(wb.worksheets[0], edits)
        wb.calculation.fullCalcOnLoad = True
        wb.save(path)
    return path, False


def read_header(path: str) -> dict:
    """Lee fecha, guía y actividad de una planilla subida, para saber a qué salida pertenece."""
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    vals = {f: ws[c].value for f, c in HEADER_CELLS.items()}
    wb.close()
    d = vals.get('date')
    if hasattr(d, 'date'):
        d = d.date()
    elif isinstance(d, str):
        try:
            dd, mm, yy = d.strip().split('/')
            d = date(int(yy), int(mm), int(dd))
        except ValueError:
            d = None
    vals['date'] = d
    return vals


def match_excursion(header: dict):
    """Busca la salida que corresponde a una planilla subida. Devuelve (salida | None, candidatas)."""
    if not header.get('date'):
        return None, []
    cands = db.find_excursions(header['date'])
    if len(cands) > 1 and header.get('guide'):
        g = str(header['guide']).lower()
        cands = [c for c in cands if (c.get('guide') or '').lower() == g] or cands
    if len(cands) > 1 and header.get('activity'):
        a = generator.resolve_activity(str(header['activity']))
        cands = [c for c in cands if generator.resolve_activity(c.get('activity') or '') == a] or cands
    return (cands[0] if len(cands) == 1 else None), cands


def save_custom(exc_id: int, uploaded_path: str) -> str:
    os.makedirs(CUSTOM_DIR, exist_ok=True)
    dest = os.path.join(CUSTOM_DIR, f'{exc_id}.xlsx')
    shutil.copy(uploaded_path, dest)
    db.set_custom_planilla(exc_id, dest)
    return dest


def drop_custom(exc_id: int):
    row = db.get_excursion(exc_id)
    if row and row.get('planilla_custom') and os.path.exists(row['planilla_custom']):
        os.remove(row['planilla_custom'])
    db.set_custom_planilla(exc_id, None)
