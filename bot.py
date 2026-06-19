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
 
 
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ''
    t = text.lower()
 
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
 
        # Guardar en DB
        exc_id = db.save_excursion({**parsed, 'planilla_path': filepath})
 
        # Google Calendar
        cal_link = calendar_service.add_excursion(parsed)
 
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
    app.add_handler(CommandHandler("testcal",  cmd_testcal))
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
