"""
Bot principal de Telegram para generación de planillas de excursiones.
"""
import os
import asyncio
import re
import logging
import tempfile
from datetime import date

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

import db
import parser as msg_parser
import generator
import scheduler as sched_module
import calendar_service
import drive_service
import ai_parser
import planillas
import sheets_service

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN       = os.environ['TELEGRAM_TOKEN']
OWNER_ID    = int(os.environ.get('TELEGRAM_OWNER_ID', '0'))  # tu chat_id

# Planillas pendientes de confirmación: (chat_id, user_id) -> parsed dict
# Lotes pendientes (varias reservas en un mensaje): (chat_id, user_id) -> [parsed, ...]
PENDING_BATCH = {}
# Última salida que tocó cada persona: los datos sueltos que mande después van ahí
LAST_EXCURSION = {}
PENDING_PLANILLAS: dict = {}


# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    db.save_setting('chat_id', str(chat_id))

    await update.message.reply_text(
        "👋 Hola! Soy tu asistente de logística.\n\n"
        "Podés pedirme cosas como:\n"
        '• _"Hace una planilla para kayak mascardi, 4 pax, el 14/4, guía Julián"_\n'
        '• _"Plani kayak tres reyes 6 pax 20/4, 2 vegetarianos"_\n'
        '• _"Plani fd kayak mascardi 3 pax 2/4 guia rodri"_\n\n'
        "Comandos disponibles:\n"
        "/proximas — ver próximas excursiones\n"
        "/gastro — gastronomía de mañana (o /gastro 25/12)\n"
        "/guias — mensajes para guías de mañana (o /guias 25/12)\n"
        "/uso — cuántos mensajes usaron IA este mes\n"
        "/backroads — servicios de Backroads de mañana\n"
        "/avisos — a dónde llegan los avisos diarios\n"
        "/version — qué versión del bot está corriendo\n\n"
        "🔔 Los avisos diarios (11 hs y 16 hs) van a llegar a este chat.",
        parse_mode='Markdown'
    )


async def cmd_proximas(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from datetime import timedelta
    today = date.today()
    lines = []
    for i in range(7):
        d = today + timedelta(days=i)
        excs = db.get_excursions_for_date(d)
        for ex in excs:
            label = "HOY" if i == 0 else ("MAÑANA" if i == 1 else d.strftime('%d/%m'))
            lines.append(
                f"*{label}* — {ex['activity']} {ex['site'] or ''} "
                f"({ex['pax']} pax) — Guía: {ex['guide'] or '—'}"
            )
    if lines:
        await update.message.reply_text(
            "📅 *Próximas 7 días:*\n\n" + '\n'.join(lines),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("No hay excursiones registradas en los próximos 7 días.")


def _fecha_pedida(ctx) -> date:
    """La fecha que pusieron después del comando; si no hay, mañana."""
    from datetime import timedelta
    args = ' '.join(getattr(ctx, 'args', None) or []).strip()
    if args:
        fecha = msg_parser.detect_date(args)
        if fecha:
            return fecha
    return date.today() + timedelta(days=1)


def _como_se_dice(fecha: date) -> str:
    from datetime import timedelta
    if fecha == date.today():
        return f"hoy ({fecha.strftime('%d/%m')})"
    if fecha == date.today() + timedelta(days=1):
        return f"mañana ({fecha.strftime('%d/%m')})"
    return f"el {fecha.strftime('%d/%m/%Y')}"


async def cmd_gastro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    fecha      = _fecha_pedida(ctx)
    excursions = db.get_excursions_for_date(fecha)
    summary    = sched_module.build_gastro_summary(excursions)
    if summary:
        await update.message.reply_text(summary, parse_mode='Markdown')
    else:
        await update.message.reply_text(
            f"No hay salidas registradas para {_como_se_dice(fecha)}.\n"
            f"_Podés pedir otro día: /gastro 25/12_", parse_mode='Markdown')


async def cmd_guias(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    fecha      = _fecha_pedida(ctx)
    excursions = db.get_excursions_for_date(fecha)
    sin_guia   = [e for e in excursions if not (e.get('guide') or '').strip()]
    messages   = sched_module.build_guide_messages(excursions)
    if not messages:
        await update.message.reply_text(
            f"No hay guías para notificar {_como_se_dice(fecha)}.\n"
            f"_Podés pedir otro día: /guias 25/12_", parse_mode='Markdown')
        return
    if sin_guia:
        detalle = '\n'.join(f"• {e.get('activity') or '—'} — {e.get('pax') or '?'} pax"
                            + (f" ({e['client']})" if e.get('client') else '')
                            for e in sin_guia)
        await update.message.reply_text(
            f"⚠️ *{len(sin_guia)} salida(s) sin guía asignado:*\n{detalle}", parse_mode='Markdown')
    for msg in messages:
        await update.message.reply_text(msg, parse_mode='Markdown')


async def cmd_testcal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    result = calendar_service.test_connection()
    await update.message.reply_text(result)


async def cmd_testdrive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Prueba de verdad el acceso a la carpeta de Drive."""
    import drive_service as ds
    await update.message.reply_text("🔎 Probando el acceso a Drive...")
    try:
        lineas = await asyncio.get_event_loop().run_in_executor(None, ds.check)
    except Exception as e:
        lineas = [f"❌ Error inesperado: {e}"]
    await update.message.reply_text('\n'.join(lineas), parse_mode='Markdown')


async def cmd_testdespachos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Prueba el acceso a la planilla DESPACHOS."""
    await update.message.reply_text("🔎 Probando la planilla DESPACHOS...")
    try:
        lineas = await asyncio.get_event_loop().run_in_executor(None, sheets_service.check)
    except Exception as e:
        lineas = [f"❌ Error inesperado: {e}"]
    await update.message.reply_text('\n'.join(lineas), parse_mode='Markdown')


async def cmd_cuenta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra la dirección de la cuenta del bot, para compartirle planillas."""
    import drive_service as ds
    mail = ds.cuenta_del_bot()
    if not mail:
        await update.message.reply_text("No encontré la cuenta del bot. ¿Está cargada GOOGLE_CREDENTIALS_JSON?")
        return
    await update.message.reply_text(
        f"La cuenta del bot es:\n`{mail}`\n\n"
        "Para que pueda escribir en una planilla o carpeta de Drive, compartísela "
        "con esa dirección y permiso de *Editor*.",
        parse_mode='Markdown')


async def handle_update_request(update: Update, upd: dict):
    """Maneja pedidos de modificación de excursiones existentes."""
    action      = upd['action']
    target_date = upd['date']
    identifier  = upd.get('identifier')
    id_type     = upd.get('identifier_type')
    new_value   = upd.get('new_value')

    # Buscar excursiones
    logger.info(f"[UPDATE] action={action} date={target_date} identifier={identifier} id_type={id_type}")
    matches = db.find_excursions(target_date, identifier, id_type)

    # Si no encontró con identificador, intentar sin él (por si el nombre no matchea exacto)
    if not matches and identifier:
        matches = db.find_excursions(target_date)

    logger.info(f"[UPDATE] matches encontrados: {len(matches)}")

    if not matches:
        hint = f" ({identifier})" if identifier else ""
        await update.message.reply_text(
            f"No encontré excursiones para el {target_date.strftime('%d/%m/%Y')}{hint}.\n"
            f"Usá /proximas para ver las salidas registradas."
        )
        return

    if len(matches) > 1:
        lines = [f"• {ex['activity']} — Guía: {ex['guide'] or '?'}" for ex in matches]
        await update.message.reply_text(
            f"Hay {len(matches)} salidas ese día. ¿Cuál querés modificar?\n" +
            '\n'.join(lines) +
            "\n\nEspecificá el nombre del guía."
        )
        return

    exc = matches[0]
    exc_id = exc['id']
    fecha_str = target_date.strftime('%d/%m/%Y')

    # ── Helper: actualiza evento en Google Calendar ───────────────────────────
    async def _sync_calendar(updated_field: str, updated_val):
        event_id = exc.get('calendar_event_id')
        if not event_id:
            return
        from datetime import date as _date
        params = dict(exc)
        try:
            params['date'] = _date.fromisoformat(params['date']) if isinstance(params['date'], str) else params['date']
        except Exception:
            return
        params[updated_field] = updated_val
        try:
            ok = calendar_service.update_excursion(event_id, params)
            if not ok:
                logger.warning(f"[Calendar] No se pudo actualizar evento {event_id}")
        except Exception as e:
            logger.error(f"[Calendar] Error actualizando evento: {e}")

    # ── Helper: regenera planilla con datos actualizados ─────────────────────
    async def _regenerate_planilla():
        resultado = await _sincronizar_despacho(exc_id)
        extra = ""
        if resultado and not resultado.get('ok'):
            extra = f"\n⚠️ En DESPACHOS no pude actualizarla: {resultado.get('error')}"
        await _send_planilla(update, exc_id, "📋 Planilla actualizada" + extra)

    if action == 'edit_item':
        nv = new_value or {}
        if not nv.get('item'):
            await update.message.reply_text(
                "No entendí qué ítem cambiar. Ej: _\"poné 4 vinos en el tronador de Rodri\"_",
                parse_mode='Markdown')
            return
        edit = {'op': nv.get('op', 'set'), 'item': nv['item'], 'qty': nv.get('qty')}
        # Simulación: aplica el cambio sobre la planilla actual para ver qué pasa
        from openpyxl import load_workbook as _lw
        with tempfile.TemporaryDirectory() as tmpdir:
            path, _ = planillas.build_file(db.get_excursion(exc_id), tmpdir)
            report = planillas.apply_item_edits(_lw(path).worksheets[0], [edit])
        msg = report[0] if report else 'Cambio guardado'
        if msg.startswith('No encontré'):
            await update.message.reply_text(f"⚠️ {msg} de {exc['activity']} ({fecha_str}). No cambié nada.")
            return
        db.add_item_edit(exc_id, edit)
        await update.message.reply_text(
            f"✅ {msg}\n{exc['activity']} — {fecha_str} (Guía: {exc['guide'] or '—'})")
        await _regenerate_planilla()
        return

    if action in ('add_extra', 'remove_extra'):
        current = generator.parse_extras(exc.get('extras'))
        asked = generator.parse_extras(new_value)
        if action == 'add_extra':
            nuevos = current + [e for e in asked if e not in current]
            verbo = 'Agregué'
        else:
            if not any(e in current for e in asked):
                # No tenía ese extra: quizás es un ítem suelto (ej. el café del Valle)
                item = msg_parser.parse_item_edit(update.message.text or '')
                if item and item['op'] == 'remove':
                    await handle_update_request(update, {**upd, 'action': 'edit_item',
                                                         'new_value': {k: v for k, v in item.items() if k != 'rest'}})
                    return
                await update.message.reply_text("Esa salida no tenía ese extra. No cambié nada.")
                return
            nuevos = [e for e in current if e not in asked]
            verbo = 'Saqué'
        db.update_excursion(exc_id, 'extras', ','.join(nuevos) or None)
        nombres = ' y '.join(generator.EXTRAS_LABEL[e] for e in asked)
        await update.message.reply_text(
            f"✅ {verbo} {nombres}\n{exc['activity']} — {fecha_str} (Guía: {exc['guide'] or '—'})")
        await _regenerate_planilla()
        return

    if action == 'set_restrictions':
        db.update_excursion(exc_id, 'dietary_restrictions', new_value)
        await _sync_calendar('dietary_restrictions', new_value)
        await update.message.reply_text(
            f"✅ Restricciones: *{new_value}*\n{exc['activity']} — {fecha_str} (Guía: {exc['guide'] or '—'})",
            parse_mode='Markdown')
        await _regenerate_planilla()
        return

    if action == 'reset_planilla':
        planillas.drop_custom(exc_id)
        db.clear_item_edits(exc_id)
        await _send_planilla(update, exc_id, "🔄 Volví a la planilla automática")
        return

    if action == 'cancel':
        db.cancel_excursion(exc_id)
        desp = await _sincronizar_despacho(exc_id, cancelada=True)
        desp_msg = ''
        if desp:
            desp_msg = ("\n📄 Marcada como CANCELADO en DESPACHOS." if desp.get('ok')
                        else "\n⚠️ No pude marcarla en DESPACHOS, revisala a mano.")
        cal_msg = ''
        if exc.get('calendar_event_id'):
            ok = calendar_service.delete_excursion(exc['calendar_event_id'])
            cal_msg = "\n📆 Evento borrado del Calendar." if ok else "\n⚠️ No pude borrar el evento del Calendar, borralo a mano."
        await update.message.reply_text(
            f"✅ Salida cancelada: {exc['activity']} — {fecha_str} "
            f"(Guía: {exc['guide'] or '—'}){cal_msg}{desp_msg}"
        )

    elif action == 'update_hora':
        if not new_value:
            await update.message.reply_text("No entendí la nueva hora. Ejemplo: _\"a las 10hs\"_", parse_mode='Markdown')
            return
        db.update_excursion(exc_id, 'hora', new_value)
        await _sync_calendar('hora', new_value)
        await update.message.reply_text(
            f"✅ Hora actualizada a *{new_value}*\n"
            f"{exc['activity']} — {fecha_str} (Guía: {exc['guide'] or '—'})",
            parse_mode='Markdown'
        )
        await _regenerate_planilla()

    elif action == 'update_guide':
        if not new_value:
            await update.message.reply_text("No entendí el nuevo guía. Ejemplo: _\"cambia el guía de la salida del 25/6 guía Julián a Rodri\"_", parse_mode='Markdown')
            return
        db.update_excursion(exc_id, 'guide', new_value)
        await _sync_calendar('guide', new_value)
        await update.message.reply_text(
            f"✅ Guía actualizado a *{new_value}*\n"
            f"{exc['activity']} — {fecha_str}",
            parse_mode='Markdown'
        )
        await _regenerate_planilla()

    elif action == 'update_date':
        if not new_value:
            await update.message.reply_text("No entendí la nueva fecha. Ejemplo: _\"cambia el día de la salida del 25/6 guía Julián al 27/6\"_", parse_mode='Markdown')
            return
        db.update_excursion(exc_id, 'date', new_value)
        await _sync_calendar('date', new_value)
        await update.message.reply_text(
            f"✅ Fecha actualizada al *{new_value.strftime('%d/%m/%Y')}*\n"
            f"{exc['activity']} — Guía: {exc['guide'] or '—'}",
            parse_mode='Markdown'
        )
        await _regenerate_planilla()

    elif action == 'update_site':
        if not new_value:
            await update.message.reply_text("No entendí el nuevo lugar. Mencioná el sitio (ej: mascardi, llao, tres reyes).")
            return
        db.update_excursion(exc_id, 'site', new_value)
        await _sync_calendar('site', new_value)
        await update.message.reply_text(
            f"✅ Lugar actualizado a *{new_value}*\n"
            f"{exc['activity']} — {fecha_str} (Guía: {exc['guide'] or '—'})",
            parse_mode='Markdown'
        )
        await _regenerate_planilla()

    elif action == 'update_pax':
        if not new_value:
            await update.message.reply_text("No entendí la nueva cantidad. Ejemplo: _\"son 6 pax ahora\"_", parse_mode='Markdown')
            return
        db.update_excursion(exc_id, 'pax', new_value)
        await _sync_calendar('pax', new_value)
        await update.message.reply_text(
            f"✅ Pax actualizado a *{new_value}*\n"
            f"{exc['activity']} — {fecha_str} (Guía: {exc['guide'] or '—'})",
            parse_mode='Markdown'
        )
        await _regenerate_planilla()

    elif action == 'update_hotel':
        if not new_value:
            await update.message.reply_text("No entendí el hotel. Ejemplo: _\"agrega el hotel Llao Llao\"_", parse_mode='Markdown')
            return
        db.update_excursion(exc_id, 'hotel', new_value)
        await update.message.reply_text(
            f"✅ Hotel actualizado a *{new_value}*\n"
            f"{exc['activity']} — {fecha_str} (Guía: {exc['guide'] or '—'})",
            parse_mode='Markdown'
        )
        await _regenerate_planilla()

    elif action == 'update_restrictions':
        if not new_value:
            await update.message.reply_text("No entendí las restricciones. Ejemplo: _\"agrega 1 celíaco\"_", parse_mode='Markdown')
            return
        combined = db.append_restrictions(exc_id, new_value)
        await _sync_calendar('dietary_restrictions', combined)
        await update.message.reply_text(
            f"✅ Restricciones actualizadas: *{combined}*\n"
            f"{exc['activity']} — {fecha_str} (Guía: {exc['guide'] or '—'})",
            parse_mode='Markdown'
        )
        await _regenerate_planilla()

    elif action == 'resend_planilla':
        row = db.get_excursion(exc_id)
        await _send_planilla(
            update, exc_id,
            f"📋 {row['activity']} — {fecha_str}\n"
            f"Guía: {row['guide'] or '—'} | Pax: {row['pax']} | Hora: {row['hora'] or '09:00 hs'}"
        )


async def _sincronizar_despacho(exc_id: int, cancelada: bool = False):
    """Refleja en la planilla DESPACHOS lo que cambió en una salida."""
    if not sheets_service.disponible():
        return None
    try:
        fila = db.get_excursion(exc_id)
        if not fila:
            return None
        return sheets_service.actualizar_despacho(fila, cancelada=cancelada)
    except Exception as e:
        logger.error(f"[Despachos] Error sincronizando: {e}")
        return {'ok': False, 'error': str(e)[:120]}


async def _send_planilla(update: Update, exc_id: int, caption: str):
    """Manda la planilla de una salida (la editada a mano si existe)."""
    try:
        row = db.get_excursion(exc_id)
        if not row:
            await update.message.reply_text("No encontré los datos de esa excursión.")
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath, editada = planillas.build_file(row, tmpdir)
            if editada:
                caption += "\n✏️ Versión editada a mano (actualicé solo la cabecera)"
            try:
                drive_service.upload_file(filepath, os.path.basename(filepath))
            except Exception as e:
                logger.error(f"[Drive] No pude subir la planilla actualizada: {e}")
            with open(filepath, 'rb') as f:
                await update.message.reply_document(
                    document=f, filename=os.path.basename(filepath), caption=caption)
    except Exception as e:
        logger.error(f"[Planilla] Error enviando: {e}")
        await update.message.reply_text("No pude armar la planilla. Intentá de nuevo.")


async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Recibe una planilla editada a mano (.xlsx) y la asocia a su salida."""
    doc = update.message.document
    if not doc or not (doc.file_name or '').lower().endswith('.xlsx'):
        return
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, 'subida.xlsx')
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(path)
        try:
            header = planillas.read_header(path)
        except Exception as e:
            logger.error(f"[Planilla] No pude leer el Excel: {e}")
            await update.message.reply_text("No pude leer ese Excel. ¿Es una planilla generada por el bot?")
            return
        exc, cands = planillas.match_excursion(header)
        if not exc:
            if not header.get('date'):
                msg = "No encontré la fecha en la planilla (celda B4). No la borres al editar."
            elif not cands:
                msg = f"No hay salidas registradas el {header['date'].strftime('%d/%m/%Y')}."
            else:
                msg = ("Hay varias salidas ese día y no pude saber cuál es. "
                       "Revisá que el guía (celda B10) coincida con el registrado.")
            await update.message.reply_text(msg)
            return
        planillas.save_custom(exc['id'], path)
    await update.message.reply_text(
        f"✅ Guardé tu planilla editada para *{exc['activity']}* del "
        f"{date.fromisoformat(exc['date']).strftime('%d/%m/%Y')} (guía {exc['guide'] or '—'}).\n"
        f"Desde ahora reenvío esta versión, y si cambia la hora, pax o guía, actualizo solo la cabecera.\n"
        f"Para volver a la planilla automática: _\"volvé a la planilla original de Lark el 20/6\"_",
        parse_mode='Markdown'
    )


def _linea_lote(i: int, p: dict) -> str:
    fecha = p['date'].strftime('%d/%m') if p.get('date') else '?'
    partes = [f"{i}. *{p.get('activity') or '(actividad?)'}*"]
    if p.get('site'):
        partes.append(p['site'])
    partes.append(f"{p.get('pax') or '?'} pax")
    partes.append(fecha)
    if p.get('guide'):
        partes.append(f"guía {p['guide']}")
    linea = ' · '.join(partes)
    extra = []
    for campo, etiqueta in (('hora', ''), ('client', 'nombre'), ('agency', 'agencia'),
                            ('hotel', 'hotel'), ('driver', 'conductor'), ('wetsuit', 'talles'),
                            ('dietary_restrictions', '')):
        if p.get(campo):
            extra.append(f"{etiqueta} {p[campo]}".strip())
    if p.get('extras'):
        extra.append(', '.join(generator.EXTRAS_LABEL[e] for e in generator.parse_extras(p['extras'])))
    if extra:
        linea += "\n     _" + ' · '.join(extra) + "_"
    faltan = msg_parser.format_missing(p)
    if faltan:
        linea += "\n     ⚠️ falta: " + ', '.join(faltan)
    return linea


async def _mostrar_lote(update: Update, key, lista: list):
    PENDING_BATCH[key] = lista
    PENDING_PLANILLAS.pop(key, None)
    cuerpo = '\n'.join(_linea_lote(i + 1, p) for i, p in enumerate(lista))
    incompletas = [i + 1 for i, p in enumerate(lista) if msg_parser.format_missing(p)]
    if incompletas:
        pie = ("\n\nFaltan datos en: " + ', '.join(f"la {n}" for n in incompletas) +
               ".\nCompletalas así: _\"en la 2 son 5 pax\"_")
    else:
        pie = ("\n\n¿Genero las {} planillas? _(sí / no)_\n"
               "Para corregir algo: _\"en la 2 el guía es Fede\"_").format(len(lista))
    await update.message.reply_text(f"Entendí {len(lista)} salidas:\n\n{cuerpo}{pie}",
                                    parse_mode='Markdown')


async def _generar_lote(update: Update, lista: list):
    await update.message.reply_text(f"⏳ Generando {len(lista)} planillas...")
    for i, p in enumerate(lista, 1):
        try:
            await _generate_and_send(update, {k: v for k, v in p.items() if not k.startswith('_')},
                                     avisar=False)
        except Exception as e:
            logger.error(f"[Lote] Error en la salida {i}: {e}")
            await update.message.reply_text(f"⚠️ No pude generar la salida {i} ({p.get('activity')}).")
    await update.message.reply_text("✅ Listo, esas son todas.")


async def _generate_and_send(update: Update, parsed: dict, avisar: bool = True):
    """Genera la planilla y la envía. Usado tanto en creación como en confirmación."""
    if avisar:
        await update.message.reply_text("⏳ Generando planilla...")

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = generator.generate(parsed, output_dir=tmpdir)

        cal_event_id = None
        cal_link = None
        try:
            cal_event_id, cal_link = calendar_service.add_excursion(parsed)
        except Exception as e:
            logger.error(f"[Calendar] Error: {e}")

        exc_id = db.save_excursion({**parsed, 'planilla_path': filepath,
                                    'calendar_event_id': cal_event_id})
        LAST_EXCURSION[(update.effective_chat.id,
                        update.effective_user.id if update.effective_user else 0)] = exc_id

        try:
            drive_link = drive_service.upload_file(filepath, os.path.basename(filepath))
        except Exception as e:
            logger.error(f"[Drive] Error: {e}")
            drive_link = None

        despacho = sheets_service.agregar_despacho({**parsed, 'id': exc_id})
        if despacho.get('ok'):
            db.update_excursion(exc_id, 'despacho_fila', despacho['fila'])

        fecha_str = parsed['date'].strftime('%d/%m/%Y') if parsed.get('date') else '—'
        caption = (
            f"✅ *{parsed['activity']}*\n"
            f"📍 {parsed.get('site') or '(completar sitio)'}\n"
            f"📅 {fecha_str}  |  👥 {parsed['pax']} pax\n"
            f"👤 Guía: {parsed.get('guide') or '(pendiente)'}"
        )
        if parsed.get('client'):
            caption += f"\n🪪 Reserva: {parsed['client']}"
        if parsed.get('hotel'):
            caption += f"\n🏨 Hotel: {parsed['hotel']}"
        if parsed.get('dietary_restrictions'):
            caption += f"\n⚠️ Restricciones: {parsed['dietary_restrictions']}"
        if cal_link:
            caption += f"\n📆 [Ver en Calendar]({cal_link})"
        if sheets_service.disponible():
            caption += ("\n📄 Anotada en DESPACHOS" + (" (día nuevo)" if despacho.get('dia_nuevo') else '')
                        if despacho.get('ok') else "\n⚠️ No pude anotarla en DESPACHOS")
        if drive_link:
            caption += f"\n📁 [Ver en Drive]({drive_link})"

        with open(filepath, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=os.path.basename(filepath),
                caption=caption,
                parse_mode='Markdown'
            )


async def handle_date_query(update: Update, query_date: date):
    """Muestra las excursiones de una fecha consultada en lenguaje natural."""
    excursions = db.get_excursions_for_date(query_date)
    # Filtrar canceladas
    excursions = [e for e in excursions if not e.get('cancelled')]

    day_names = ['lunes','martes','miércoles','jueves','viernes','sábado','domingo']
    day_name = day_names[query_date.weekday()]
    fecha_str = f"{day_name} {query_date.strftime('%d/%m/%Y')}"

    if not excursions:
        await update.message.reply_text(f"No hay salidas registradas para el {fecha_str}.")
        return

    lines = [f"📅 *Salidas del {fecha_str}:*\n"]
    for ex in excursions:
        hora = ex.get('hora') or '09:00 hs'
        guide = ex.get('guide') or '(sin guía)'
        hotel = f" — Hotel: {ex['hotel']}" if ex.get('hotel') else ''
        pax = ex.get('pax') or '?'
        restr = f"\n   ⚠️ {ex['dietary_restrictions']}" if ex.get('dietary_restrictions') else ''
        lines.append(
            f"• *{ex['activity']}* {ex.get('site') or ''}\n"
            f"   🕐 {hora} | 👥 {pax} pax | 👤 {guide}{hotel}{restr}"
        )

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


def _resumen_borrador(parsed: dict) -> str:
    fecha_str = parsed['date'].strftime('%d/%m/%Y') if parsed.get('date') else '—'
    resumen = (
        f"Entendí esto:\n"
        f"• *{parsed.get('activity') or '(actividad?)'}* — {parsed.get('site') or '(sitio no especificado)'}\n"
        f"• Fecha: {fecha_str}  |  Pax: {parsed.get('pax') or '?'}\n"
        f"• Guía: {parsed.get('guide') or '(no especificado)'}"
    )
    if parsed.get('client'):
        resumen += f"\n• Nombre: {parsed['client']}"
    if parsed.get('agency'):
        resumen += f"\n• Agencia: {parsed['agency']}"
    if parsed.get('hotel'):
        resumen += f"\n• Hotel: {parsed['hotel']}"
    if parsed.get('personal'):
        resumen += f"\n• Personal: {parsed['personal']}"
    if parsed.get('driver'):
        resumen += f"\n• Conductor: {parsed['driver']}"
    if parsed.get('wetsuit'):
        resumen += f"\n• Talles neoprene: {parsed['wetsuit']}"
    if parsed.get('hora'):
        resumen += f"\n• Hora de retiro: {parsed['hora']}"
    if parsed.get('hora_entrega'):
        resumen += f"\n• Entrega del despacho: {parsed['hora_entrega']}"
    if parsed.get('dietary_restrictions'):
        resumen += f"\n• Restricciones: {parsed['dietary_restrictions']}"
    extras = generator.parse_extras(parsed.get('extras'))
    if extras:
        resumen += "\n• Extras: " + ', '.join(generator.EXTRAS_LABEL[e] for e in extras)
    return resumen


async def _handle_create(update: Update, key, parsed: dict):
    """Muestra el borrador: pide lo que falta o pide confirmación."""
    if parsed.get('activity') and not parsed.get('site'):
        parsed = {**parsed, 'site': generator.default_site(parsed['activity'])}
    missing = msg_parser.format_missing(parsed)
    PENDING_PLANILLAS[key] = {**parsed, '_complete': not missing}
    if missing:
        extra = ("\n\nRespondé solo con lo que falta (ej: _\"6 pax\"_) y lo completo."
                 if ai_parser.available() else
                 "\n\nMandame el pedido completo de nuevo con esos datos.")
        await update.message.reply_text(
            _resumen_borrador(parsed) + "\n\nFaltaría:\n• " + '\n• '.join(missing) + extra,
            parse_mode='Markdown'
        )
        return
    await update.message.reply_text(
        _resumen_borrador(parsed) + "\n\n¿Genero la planilla? _(sí / no, o decime qué corregir)_",
        parse_mode='Markdown'
    )


def _resolve_without_date(upd: dict) -> dict:
    """Si una modificación no dice la fecha pero sí el guía/reserva, busca en las próximas salidas."""
    if upd.get('date') or not upd.get('identifier'):
        return upd
    ident = upd['identifier'].lower()
    hits = [e for e in db.get_upcoming(days=90)
            if ident in (e.get('guide') or '').lower() or ident in (e.get('client') or '').lower()]
    if len(hits) == 1:
        upd = {**upd, 'date': date.fromisoformat(hits[0]['date'])}
    return upd


def _fill_known_guide(parsed: dict, text: str) -> dict:
    """Si no se detectó guía pero el texto nombra a uno ya conocido ("con rodri"), lo completa."""
    if parsed.get('guide'):
        return parsed
    for g in db.known_guides():
        first = g.split()[0]
        if len(first) >= 3 and re.search(rf'\b{re.escape(first.lower())}\b', text.lower()):
            return {**parsed, 'guide': g}
    return parsed


GREETING = re.compile(r'^(hola|buenas|buen[oa]s?\s+(d[ií]as?|tardes?|noches?)|gracias|genial|joya|perfecto|ok gracias|ayuda|help)\b[\s!.,?¿¡a-záéíóúñ]*$', re.I)


ETIQUETAS = {
    'client': 'Nombre', 'agency': 'Agencia', 'hotel': 'Hotel', 'driver': 'Transporte',
    'guide': 'Guía', 'hora': 'Horario', 'wetsuit': 'Talles', 'pax': 'Pax',
    'personal': 'Personal', 'site': 'Sitio', 'dietary_restrictions': 'Restricciones',
}


async def _aplicar_campos(update: Update, exc_id: int, exc: dict, campos: dict):
    """Completa varios datos de una salida ya cargada y reenvía la planilla."""
    aplicados = []
    for campo, valor in campos.items():
        db.update_excursion(exc_id, campo, valor)
        aplicados.append(f"{ETIQUETAS.get(campo, campo)}: {valor}")
    fecha = date.fromisoformat(exc['date']).strftime('%d/%m') if isinstance(exc['date'], str) else exc['date'].strftime('%d/%m')
    await update.message.reply_text(
        "✅ Lo sumé a *{}* del {} (guía {}):\n• {}".format(
            exc.get('activity'), fecha, exc.get('guide') or '—', '\n• '.join(aplicados)),
        parse_mode='Markdown')
    await _send_planilla(update, exc_id, "📋 Planilla actualizada")


async def _handle_backroads(update: Update, datos: dict):
    """Completa un servicio en la planilla de Backroads."""
    if not sheets_service.backroads_disponible():
        await update.message.reply_text(
            "La planilla de Backroads no está configurada todavía (falta BACKROADS_SHEET_ID).")
        return
    if not datos.get('fecha'):
        await update.message.reply_text(
            "¿De qué fecha? Ej: _\"Backroads Multi Adventure del 9/12, 12 pax, 2 veggie\"_",
            parse_mode='Markdown')
        return
    if datos.get('pax') is None and datos.get('personal') is None and not datos.get('dietas'):
        await update.message.reply_text(
            "¿Qué completo? Decime los pax, el personal o las dietas.\n"
            "Ej: _\"Backroads Regular del 22/11, 13 pax, 4 perso, 1 veggie y 3 pescetarian\"_",
            parse_mode='Markdown')
        return

    resultado = await asyncio.get_event_loop().run_in_executor(
        None, lambda: sheets_service.backroads_completar(
            datos['fecha'], datos.get('grupo'), datos.get('actividad'),
            datos.get('pax'), datos.get('personal'), datos.get('dietas')))

    if not resultado.get('ok'):
        texto = f"⚠️ {resultado.get('error')}"
        if resultado.get('opciones'):
            texto += "\n\n" + '\n'.join(f"• {o}" for o in resultado['opciones'])
            texto += "\n\n_Decime cuál agregando el grupo o la actividad._"
        await update.message.reply_text(texto, parse_mode='Markdown')
        return

    s = resultado['servicio']
    partes = []
    if datos.get('pax') is not None:
        partes.append(f"{datos['pax']} pax")
    if datos.get('personal') is not None:
        partes.append(f"{datos['personal']} perso")
    for dieta, valor in (datos.get('dietas') or {}).items():
        partes.append(f"{valor} {dieta}")
    await update.message.reply_text(
        f"✅ Completé *{s['grupo']} · {s['actividad'] or 'sin actividad'}* "
        f"del {s['fecha'].strftime('%d/%m/%Y')} ({s['servicio']}):\n• " + '\n• '.join(partes),
        parse_mode='Markdown')


async def cmd_backroads(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """La reconfirmación de Backroads de mañana, o de la fecha que pidan."""
    fecha = _fecha_pedida(ctx)
    texto = await asyncio.get_event_loop().run_in_executor(
        None, lambda: sheets_service.backroads_reconfirmacion(fecha))
    await update.message.reply_text(
        texto or f"No hay servicios de Backroads {_como_se_dice(fecha)}.", parse_mode='Markdown')


async def cmd_testbackroads(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 Probando la planilla de Backroads...")
    try:
        lineas = await asyncio.get_event_loop().run_in_executor(None, sheets_service.backroads_check)
    except Exception as e:
        lineas = [f"❌ Error inesperado: {e}"]
    await update.message.reply_text('\n'.join(lineas), parse_mode='Markdown')


async def _via_ai(update: Update, key, text: str) -> bool:
    """Le pasa el mensaje a la IA. Devuelve True si lo resolvió."""
    if not ai_parser.available():
        return False
    pending = PENDING_PLANILLAS.get(key)
    pending_clean = {k: v for k, v in pending.items() if k != '_complete'} if pending else None
    result = ai_parser.interpret(text, upcoming=db.get_upcoming(), pending=pending_clean)
    if not result:
        return False
    db.incr_counter('ia')
    intent = result['intent']
    if intent == 'create_batch':
        await _mostrar_lote(update, key, result['data'])
    elif intent == 'create':
        await _handle_create(update, key, result['data'])
    elif intent == 'query':
        await handle_date_query(update, result['date'])
    elif intent == 'update':
        await handle_update_request(update, result['data'])
    else:
        await update.message.reply_text(
            result.get('reply') or
            "No entendí el pedido. Probá con algo como:\n_\"Kayak mascardi 4 pax 14/4 guía Julián\"_",
            parse_mode='Markdown'
        )
    return True


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Modelo mixto: primero reglas (gratis, instantáneo). Solo si las reglas
    no están seguras, el mensaje pasa a la IA. Sin IA configurada, las reglas
    hacen todo lo que pueden y piden aclaración.
    """
    text = update.message.text or ''
    t = text.lower().strip()
    key = (update.effective_chat.id, update.effective_user.id if update.effective_user else 0)
    pending = PENDING_PLANILLAS.get(key)

    # Si nadie mandó /start todavía, los avisos diarios van a este chat
    if not db.get_setting('chat_id'):
        db.save_setting('chat_id', str(update.effective_chat.id))
        logger.info(f"Chat de avisos fijado automáticamente en {update.effective_chat.id}.")

    # 1. Confirmación / cancelación del borrador ───────────────────────────────
    if re.search(r'^s[ií]!*$|^dale$|^ok$|^generar?(la)?s?$|^confirm[ao]$|^anda$|^va$|^de una$|^todas?$', t):
        lote = PENDING_BATCH.get(key)
        if lote:
            if any(msg_parser.format_missing(p) for p in lote):
                await _mostrar_lote(update, key, lote)
                return
            PENDING_BATCH.pop(key, None)
            db.incr_counter('reglas')
            await _generar_lote(update, lote)
            return
        if pending and pending.get('_complete'):
            PENDING_PLANILLAS.pop(key, None)
            await _generate_and_send(update, {k: v for k, v in pending.items() if k != '_complete'})
            return
    if re.search(r'^no$|^cancel[ao]$|^nop[eo]?$|^dej[aá]$', t):
        if PENDING_BATCH.pop(key, None):
            await update.message.reply_text("Cancelado, no generé ninguna.")
            return
        if PENDING_PLANILLAS.pop(key, None):
            await update.message.reply_text("Cancelado. Podés mandarme el pedido de nuevo cuando quieras.")
            return

    # 2. Corregir una salida del lote pendiente ("en la 2 el guía es Fede") ────
    lote = PENDING_BATCH.get(key)
    if lote:
        ref = msg_parser.parse_correccion_lote(text, len(lote))
        if ref:
            idx, resto = ref
            merged = msg_parser.merge_followup(resto, lote[idx]) if resto else None
            if merged:
                lote[idx] = merged
                db.incr_counter('reglas')
                await _mostrar_lote(update, key, lote)
                return
            await update.message.reply_text(
                f"No entendí qué cambiar en la {idx + 1}. Probá: _\"en la {idx + 1} son 5 pax\"_",
                parse_mode='Markdown')
            return
        if msg_parser.mentions_activity(text) or msg_parser.parse_reservas(text):
            PENDING_BATCH.pop(key, None)      # pedido nuevo: se descarta el lote anterior

    # 3. Completar / corregir el borrador pendiente ────────────────────────────
    if pending:
        clean = {k: v for k, v in pending.items() if k != '_complete'}
        merged = msg_parser.merge_followup(text, clean)
        if not merged and not clean.get('guide') and len(text.split()) <= 3:
            filled = _fill_known_guide(clean, text)
            merged = filled if filled is not clean else None
        if merged:
            db.incr_counter('reglas')
            await _handle_create(update, key, merged)
            return

    # Datos sueltos que completan la última salida cargada
    #    ("Nombre: oram david / Agencia: aliwen / Hotel: peninsula petit")
    if not msg_parser.mentions_activity(text):
        sueltos = msg_parser.campos_sueltos(text)
        if sueltos and LAST_EXCURSION.get(key):
            exc_id = LAST_EXCURSION[key]
            exc = db.get_excursion(exc_id)
            if exc and not exc.get('cancelled'):
                db.incr_counter('reglas')
                await _aplicar_campos(update, exc_id, exc, sueltos)
                return

    # Backroads: completar un servicio ya cargado en su planilla
    br = msg_parser.parse_backroads(text)
    if br:
        db.incr_counter('reglas')
        await _handle_backroads(update, br)
        return

    # 4. Consulta de fecha ("qué hay el viernes") ──────────────────────────────
    query_date = msg_parser.parse_date_query(text)
    if query_date:
        db.incr_counter('reglas')
        await handle_date_query(update, query_date)
        return

    # 5. Modificación de una salida existente ──────────────────────────────────
    upd = msg_parser.parse_update(text)
    if upd:
        upd = _resolve_without_date(upd)
        if msg_parser.update_is_complete(upd):
            db.incr_counter('reglas')
            await handle_update_request(update, upd)
            return
        if await _via_ai(update, key, text):
            return
        if upd.get('date'):
            await handle_update_request(update, upd)   # pide el dato que falta
        else:
            await update.message.reply_text(
                "¿De qué salida? Decime la fecha y el guía (ej: _\"del 20/6 guía Lark\"_).",
                parse_mode='Markdown')
        return

    # 6. Varias reservas en un mismo mensaje ───────────────────────────────────
    lista = msg_parser.parse_reservas(text)
    if len(lista) >= 2:
        db.incr_counter('reglas')
        await _mostrar_lote(update, key, lista)
        return

    # 7. Pedido de planilla nueva ──────────────────────────────────────────────
    if msg_parser.mentions_activity(text):
        parsed = _fill_known_guide(msg_parser.parse_message(text), text)
        if not msg_parser.format_missing(parsed):
            db.incr_counter('reglas')
            await _handle_create(update, key, parsed)   # siempre pide confirmación
            return
        db.incr_counter('reglas')
        await _handle_create(update, key, parsed)       # pide lo que falta (sin gastar IA)
        return

    # 8. Saludos / ayuda: respuesta fija, sin IA ───────────────────────────────
    if len(t) < 40 and GREETING.match(t):
        await update.message.reply_text(
            "👋 Mandame una salida y te armo la planilla, ej:\n"
            "_\"Kayak mascardi 4 pax 20/6 guía Lark\"_\n"
            "O preguntame _\"qué hay mañana\"_.",
            parse_mode='Markdown')
        return

    # 9. Nada claro: IA, o mensaje de ayuda ────────────────────────────────────
    if await _via_ai(update, key, text):
        return
    await update.message.reply_text(
        "No entendí el pedido. Intentá con algo como:\n"
        "_\"Kayak mascardi 4 pax 14/4 guía Julián\"_",
        parse_mode='Markdown'
    )


VERSION = "v15 — 21/11/2026"
NOVEDADES = [
    "Mensajes largos con todos los datos juntos",
    "Varias reservas en un mismo mensaje",
    "Agencia, conductor, talles y personal",
    "Extras de día frío (infusiones y sopa)",
    "Editar ítems de la planilla por chat",
    "Reconfirmación de gastronomía con códigos (AC, BLG, EEPP…)",
    "Planillas con nombre tipo «21-11 Valle Encantado Asado x2»",
    "Códigos de gastronomía unificados (AC, BLG, BLT, EEPP, EPP, snacks)",
    "Backup diario de la base a Drive",
    "Aviso de salidas sin guía asignado",
    "/gastro y /guias de cualquier fecha",
    "Escribe cada reserva en la planilla DESPACHOS",
    "Completa la planilla de Backroads y reconfirma el día anterior",
]


async def cmd_version(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 *Bot de Logística {VERSION}*\n"
        f"Salidas cargadas: {len(generator.TEMPLATES)}\n"
        f"Interpretación con IA: {'activada' if ai_parser.available() else 'desactivada'}\n\n"
        "Incluye:\n• " + '\n• '.join(NOVEDADES),
        parse_mode='Markdown')


async def cmd_avisos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Diagnóstico de los avisos diarios: a dónde van y cuándo salen."""
    from datetime import datetime
    aqui = update.effective_chat.id
    arg = (ctx.args[0].lower() if getattr(ctx, 'args', None) else '')
    if arg in ('aca', 'acá', 'aqui', 'aquí'):
        db.save_setting('chat_id', str(aqui))
        await update.message.reply_text("✅ Desde ahora los avisos diarios llegan a este chat.")
        return

    destino = db.get_setting('chat_id')
    ahora = datetime.now(sched_module.TZ)
    lineas = [f"🕐 Hora del bot: {ahora.strftime('%d/%m %H:%M')} (hora de Argentina)"]
    if not destino:
        lineas.append("⚠️ *No hay chat configurado*: por eso no llegan los avisos.\n"
                      "Mandá `/avisos aca` en el chat donde los querés recibir.")
    elif str(aqui) == destino:
        lineas.append("📬 Los avisos llegan *a este chat*.")
    else:
        lineas.append(f"📬 Los avisos llegan a *otro chat* (id {destino}).\n"
                      "Si los querés acá, mandá `/avisos aca`.")

    sched = getattr(sched_module, 'SCHEDULER', None)
    if sched:
        for job in sched.get_jobs():
            nombre = {'gastro_summary': 'Gastronomía (11 hs)',
                      'guide_messages': 'Guías (16 hs)',
                      'backroads': 'Backroads (10:45)',
                      'backup_db': 'Backup de la base (3:30)'}.get(job.id, job.id)
            prox = job.next_run_time.strftime('%d/%m %H:%M') if job.next_run_time else '—'
            lineas.append(f"• {nombre}: próximo envío {prox}")
    else:
        lineas.append("⚠️ El programador de avisos no está corriendo. Reiniciá el bot en Railway.")

    lineas.append("\n_Para probar el contenido ahora mismo: /gastro y /guias._")
    await update.message.reply_text('\n'.join(lineas), parse_mode='Markdown')


async def cmd_uso(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    reglas = db.get_counter('reglas')
    ia = db.get_counter('ia')
    total = reglas + ia
    pct = f" ({ia * 100 // total}% con IA)" if total else ''
    costo = ia * 0.0003
    await update.message.reply_text(
        f"📊 Mensajes interpretados este mes: {total}{pct}\n"
        f"• Por reglas (gratis): {reglas}\n"
        f"• Por IA: {ia} — costo estimado ≈ US$ {costo:.2f}\n"
        f"IA {'activada' if ai_parser.available() else 'desactivada'}."
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    db.init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("proximas", cmd_proximas))
    app.add_handler(CommandHandler("gastro",   cmd_gastro))
    app.add_handler(CommandHandler("guias",    cmd_guias))
    app.add_handler(CommandHandler("uso",       cmd_uso))
    app.add_handler(CommandHandler("avisos",    cmd_avisos))
    app.add_handler(CommandHandler("version",   cmd_version))
    app.add_handler(CommandHandler("cuenta",    cmd_cuenta))
    app.add_handler(CommandHandler("testdespachos", cmd_testdespachos))
    app.add_handler(CommandHandler("backroads",     cmd_backroads))
    app.add_handler(CommandHandler("testbackroads", cmd_testbackroads))
    app.add_handler(CommandHandler("testcal",   cmd_testcal))
    app.add_handler(CommandHandler("testdrive", cmd_testdrive))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Iniciar scheduler después de que el event loop esté corriendo
    async def post_init(app):
        # El scheduler arranca siempre; el chat de destino se lee en cada aviso,
        # así que funciona aunque /start se mande después de iniciar el bot.
        sched_module.setup_scheduler(app.bot)
        if not db.get_setting('chat_id'):
            logger.warning("chat_id no configurado aún. Enviá /start al bot para activar los recordatorios.")

    app.post_init = post_init

    logger.info(f"Bot iniciado — {VERSION}. Interpretación con IA: {'activada' if ai_parser.available() else 'desactivada (falta ANTHROPIC_API_KEY)'}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
