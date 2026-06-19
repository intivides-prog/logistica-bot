"""
Bot principal de Telegram para generación de planillas de excursiones.
"""
import os
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
 
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
 
TOKEN       = os.environ['TELEGRAM_TOKEN']
OWNER_ID    = int(os.environ.get('TELEGRAM_OWNER_ID', '0'))  # tu chat_id
 
 
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
        "/gastro — resumen de gastronomía de mañana\n"
        "/guias — mensaje para guías de mañana",
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
 
 
async def cmd_gastro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from datetime import timedelta
    tomorrow   = date.today() + timedelta(days=1)
    excursions = db.get_excursions_for_date(tomorrow)
    summary    = sched_module.build_gastro_summary(excursions)
    if summary:
        await update.message.reply_text(summary, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"No hay salidas registradas para mañana ({tomorrow.strftime('%d/%m/%Y')}).")
 
 
async def cmd_guias(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from datetime import timedelta
    tomorrow   = date.today() + timedelta(days=1)
    excursions = db.get_excursions_for_date(tomorrow)
    messages   = sched_module.build_guide_messages(excursions)
    if messages:
        for msg in messages:
            await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"No hay guías para notificar mañana ({tomorrow.strftime('%d/%m/%Y')}).")
 
 
async def cmd_testcal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    result = calendar_service.test_connection()
    await update.message.reply_text(result)
 
 
async def cmd_testdrive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import drive_service as ds
    folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', '(no configurado)')
    creds_ok = bool(os.environ.get('GOOGLE_CREDENTIALS_JSON'))
    await update.message.reply_text(
        f"GOOGLE_DRIVE_FOLDER_ID: {folder_id}\n"
        f"GOOGLE_CREDENTIALS_JSON: {'✅ presente' if creds_ok else '❌ ausente'}\n"
        f"GOOGLE_AVAILABLE: {ds.GOOGLE_AVAILABLE}"
    )
 
 
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
        try:
            from datetime import date as _date
            exc_date = _date.fromisoformat(exc['date']) if isinstance(exc['date'], str) else exc['date']
            rows = db.find_excursions(exc_date)
            row = next((e for e in rows if e['id'] == exc_id), None)
            if not row:
                return
            row_date = _date.fromisoformat(row['date']) if isinstance(row['date'], str) else row['date']
            from generator import generate_planilla
            params = {**row, 'date': row_date}
            filepath, filename = generate_planilla(params)
            with open(filepath, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    filename=filename,
                    caption="📋 Planilla actualizada"
                )
        except Exception as e:
            logger.error(f"[Planilla] Error regenerando: {e}")
 
    if action == 'cancel':
        db.cancel_excursion(exc_id)
        await update.message.reply_text(
            f"✅ Salida cancelada: {exc['activity']} — {fecha_str} "
            f"(Guía: {exc['guide'] or '—'})"
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
        await update.message.reply_text(
            f"✅ Restricciones actualizadas: *{combined}*\n"
            f"{exc['activity']} — {fecha_str} (Guía: {exc['guide'] or '—'})",
            parse_mode='Markdown'
        )
        await _regenerate_planilla()
 
 
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ''
    t = text.lower()
 
    # Detectar si es una actualización
    upd = msg_parser.parse_update(text)
    if upd:
        await handle_update_request(update, upd)
        return
 
    # Solo responder si parece un pedido de planilla
    keywords = ['plani', 'planilla', 'kayak', 'mtb', 'trekking', 'naveg']
    if not any(k in t for k in keywords):
        await update.message.reply_text(
            "No entendí el pedido. Intentá con algo como:\n"
            "_\"Planilla kayak mascardi 4 pax 14/4 guía Julián\"_",
            parse_mode='Markdown'
        )
        return
 
    # Parsear mensaje
    parsed = msg_parser.parse_message(text)
    missing = msg_parser.format_missing(parsed)
 
    if missing:
        await update.message.reply_text(
            f"Casi! Faltaría:\n• " + '\n• '.join(missing) +
            "\n\nAgregá esos datos y lo genero al toque.",
            parse_mode='Markdown'
        )
        return
 
    # Guardar chat_id si no está
    db.save_setting('chat_id', str(update.effective_chat.id))
 
    # Generar planilla
    await update.message.reply_text("⏳ Generando planilla...")
 
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = generator.generate(parsed, output_dir=tmpdir)
 
        # (exc_id ya guardado arriba con calendar_event_id)
 
        # Google Calendar
        cal_event_id = None
        cal_link = None
        try:
            cal_event_id, cal_link = calendar_service.add_excursion(parsed)
        except Exception as e:
            logger.error(f"[Calendar] Error: {e}")
 
        # Guardar en DB con event_id
        exc_id = db.save_excursion({**parsed, 'planilla_path': filepath, 'calendar_event_id': cal_event_id})
 
        # Google Drive
        try:
            drive_link = drive_service.upload_file(filepath, os.path.basename(filepath))
        except Exception as e:
            logger.error(f"[Drive] Error: {e}")
            drive_link = None
 
        # Armar respuesta
        fecha_str = parsed['date'].strftime('%d/%m/%Y') if parsed.get('date') else '—'
        caption = (
            f"✅ *{parsed['activity']}*\n"
            f"📍 {parsed.get('site') or '(completar sitio)'}\n"
            f"📅 {fecha_str}  |  👥 {parsed['pax']} pax\n"
            f"👤 Guía: {parsed.get('guide') or '(pendiente)'}"
        )
        if parsed.get('dietary_restrictions'):
            caption += f"\n⚠️ Restricciones: {parsed['dietary_restrictions']}"
        if cal_link:
            caption += f"\n📆 [Ver en Calendar]({cal_link})"
        if drive_link:
            caption += f"\n📁 [Ver en Drive]({drive_link})"
 
        # Enviar archivo
        with open(filepath, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=os.path.basename(filepath),
                caption=caption,
                parse_mode='Markdown'
            )
 
 
# ── Entry point ───────────────────────────────────────────────────────────────
 
def main():
    db.init_db()
 
    app = Application.builder().token(TOKEN).build()
 
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("proximas", cmd_proximas))
    app.add_handler(CommandHandler("gastro",   cmd_gastro))
    app.add_handler(CommandHandler("guias",    cmd_guias))
    app.add_handler(CommandHandler("testcal",   cmd_testcal))
    app.add_handler(CommandHandler("testdrive", cmd_testdrive))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
 
    # Iniciar scheduler después de que el event loop esté corriendo
    async def post_init(app):
        chat_id_str = db.get_setting('chat_id')
        if chat_id_str:
            sched_module.setup_scheduler(app.bot, int(chat_id_str))
        else:
            logger.warning("chat_id no configurado aún. Enviá /start al bot para activar los recordatorios.")
 
    app.post_init = post_init
 
    logger.info("Bot iniciado.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
 
 
if __name__ == '__main__':
    main()
