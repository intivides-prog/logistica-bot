"""
Tareas programadas:
  11:00 hs → resumen de gastronomía para el día siguiente
  16:00 hs → mensaje para reenviar al guía
Zona horaria: America/Argentina/Buenos_Aires
"""
import asyncio
from datetime import date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import db
import generator

TZ = pytz.timezone('America/Argentina/Buenos_Aires')

GASTRO_LABELS = {
    'AC':     'Almuerzo Campestre',
    'snacks': 'Snacks HD',
}


def build_gastro_summary(excursions: list) -> str:
    if not excursions:
        return None

    target_date = excursions[0]['date']
    lines = [f"🍽️  *GASTRONOMÍA — {target_date}*\n"]

    totals = {}
    for ex in excursions:
        gtype  = ex.get('gastronomy_type') or 'AC'
        tmpl   = generator.TEMPLATES.get(generator.resolve_activity(ex.get('activity') or ''))
        if tmpl and tmpl.get('gastronomy_title'):
            label = tmpl['gastronomy_title'].split('—')[-1].strip().title()
        else:
            label = GASTRO_LABELS.get(gtype, gtype)
        pax    = ex.get('pax') or '?'
        client = ex.get('client') or ex.get('guide') or '—'
        diet   = ex.get('dietary_restrictions')

        # Formato: "Ciardelli : AC x4 ( 1 vegetariano)"
        line = f"• *{client}* : {label} x{pax}"
        extras = generator.parse_extras(ex.get('extras'))
        if extras:
            line += " + " + " + ".join(generator.EXTRAS_LABEL[e] for e in extras)
        if diet:
            line += f" ( {diet} )"
        lines.append(line)

        totals[label] = totals.get(label, 0) + (pax if isinstance(pax, int) else 0)

    if len(totals) > 1 or sum(totals.values()) > 0:
        lines.append("")
        for label, total in totals.items():
            lines.append(f"_Total {label}: {total} pax_")

    return '\n'.join(lines)


def build_guide_messages(excursions: list) -> list[str]:
    messages = []
    for ex in excursions:
        guide = ex.get('guide') or 'Guía'
        activity = ex.get('activity') or '—'
        site     = ex.get('site') or '—'
        hora     = ex.get('hora') or 'a confirmar'
        pax      = ex.get('pax') or '—'
        diet     = ex.get('dietary_restrictions')

        msg_guia = (
            f"Hola {guide}! Te recuerdo que mañana tenemos:\n"
            f"📍 {activity} — {site}\n"
            f"🕐 {hora}\n"
            f"👥 {pax} pax"
        )
        if diet:
            msg_guia += f"\n⚠️ Restricciones: {diet}"

        telegram_msg = (
            f"📋 *RECORDATORIO GUÍA — {ex['date']}*\n\n"
            f"Guía: *{guide}*\n"
            f"Excursión: {activity} — {site}\n"
            f"Hora: {hora} | Pax: {pax}\n\n"
            f"*Mensaje para reenviar por WhatsApp:*\n"
            f"```\n{msg_guia}\n```"
        )
        messages.append(telegram_msg)
    return messages


def _notify_chat_id():
    """Chat donde van los avisos: el último donde se mandó /start."""
    val = db.get_setting('chat_id')
    return int(val) if val else None


async def job_gastro_summary(bot):
    chat_id = _notify_chat_id()
    if not chat_id:
        print("[Scheduler] Sin chat configurado: mandá /start al bot.")
        return
    tomorrow = date.today() + timedelta(days=1)
    excursions = db.get_excursions_for_date(tomorrow)
    summary = build_gastro_summary(excursions)
    if summary:
        await bot.send_message(chat_id=chat_id, text=summary, parse_mode='Markdown')
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ No hay salidas registradas para mañana ({tomorrow.strftime('%d/%m/%Y')})."
        )


async def job_guide_messages(bot):
    chat_id = _notify_chat_id()
    if not chat_id:
        print("[Scheduler] Sin chat configurado: mandá /start al bot.")
        return
    tomorrow = date.today() + timedelta(days=1)
    excursions = db.get_excursions_for_date(tomorrow)
    messages = build_guide_messages(excursions)
    if messages:
        for msg in messages:
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ No hay guías que notificar mañana ({tomorrow.strftime('%d/%m/%Y')})."
        )


def setup_scheduler(bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TZ)

    scheduler.add_job(
        lambda: asyncio.ensure_future(job_gastro_summary(bot)),
        CronTrigger(hour=11, minute=0, timezone=TZ),
        id='gastro_summary',
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: asyncio.ensure_future(job_guide_messages(bot)),
        CronTrigger(hour=16, minute=0, timezone=TZ),
        id='guide_messages',
        replace_existing=True,
    )

    scheduler.start()
    return scheduler
