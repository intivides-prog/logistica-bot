"""
Tareas programadas:
  11:00 hs → resumen de gastronomía para el día siguiente
  16:00 hs → mensaje para reenviar al guía
Zona horaria: America/Argentina/Buenos_Aires
"""
import asyncio
import re
import logging
from datetime import date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import db
import generator

logger = logging.getLogger(__name__)

TZ = pytz.timezone('America/Argentina/Buenos_Aires')

GASTRO_LABELS = {
    'AC':     'Almuerzo Campestre',
    'snacks': 'Snacks HD',
}


def _restricciones_cortas(diet: str) -> str:
    """'2x vegetariano/a, 1x celíaco/a (sin TACC)' → '2 vegetariano - 1 celíaco'."""
    if not diet:
        return ''
    partes = []
    for p in str(diet).split(','):
        p = re.sub(r'\s*\([^)]*\)', '', p).strip()        # saca las aclaraciones entre paréntesis
        p = re.sub(r'^(\d+)\s*x\s*', r'\1 ', p)            # "2x vegetariano" → "2 vegetariano"
        p = re.sub(r'/[ao]s?\b', '', p)                     # "celíaco/a" → "celíaco"
        p = p.strip(' .')
        if p:
            partes.append(p)
    return ' - '.join(partes)


def build_gastro_summary(excursions: list) -> str:
    """
    Reconfirmación de gastronomía, una línea por salida:
        2 AC + 2 perso - *Winebar*
        2 EEPP (1 no cerdo - 1 pescatariano) + 1 perso - *Jacobs*
    """
    if not excursions:
        return None

    target_date = excursions[0]['date']
    if hasattr(target_date, 'strftime'):
        fecha = target_date.strftime('%d/%m')
    else:
        try:
            fecha = date.fromisoformat(str(target_date)).strftime('%d/%m')
        except ValueError:
            fecha = str(target_date)

    lines = [f"🍽️ *GASTRONOMÍA — {fecha}*\n"]
    totals = {}
    for ex in excursions:
        actividad = ex.get('activity') or ''
        codigo = generator.gastro_code(actividad)
        pax = ex.get('pax') or 0
        personal = ex.get('personal') or generator.default_personal(actividad)
        nombre = ex.get('client') or ex.get('agency') or ex.get('guide') or '—'

        linea = f"{pax} {codigo}"
        rest = _restricciones_cortas(ex.get('dietary_restrictions'))
        if rest:
            linea += f" ({rest})"
        linea += f" + {personal} perso - *{nombre}*"
        extras = generator.parse_extras(ex.get('extras'))
        if extras:
            linea += " + " + " + ".join(generator.EXTRAS_LABEL[e] for e in extras)
        lines.append(linea)

        if isinstance(pax, int):
            totals[codigo] = totals.get(codigo, 0) + pax + (personal or 0)

    if totals:
        lines.append("")
        lines.append("_Totales (con personal): " +
                     ' · '.join(f"{c} {n}" for c, n in totals.items()) + "_")

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
    logger.info("[Scheduler] Corriendo aviso de gastronomía (11 hs).")
    chat_id = _notify_chat_id()
    if not chat_id:
        logger.warning("[Scheduler] Sin chat configurado: mandá /start al bot.")
        return
    tomorrow = date.today() + timedelta(days=1)
    excursions = db.get_excursions_for_date(tomorrow)
    summary = build_gastro_summary(excursions)
    texto = summary or f"✅ No hay salidas registradas para mañana ({tomorrow.strftime('%d/%m/%Y')})."
    try:
        await bot.send_message(chat_id=chat_id, text=texto, parse_mode='Markdown')
        logger.info(f"[Scheduler] Aviso de gastronomía enviado a {chat_id}.")
    except Exception as e:
        logger.error(f"[Scheduler] No pude enviar el aviso de gastronomía a {chat_id}: {e}")


async def job_guide_messages(bot):
    logger.info("[Scheduler] Corriendo mensajes para guías (16 hs).")
    chat_id = _notify_chat_id()
    if not chat_id:
        logger.warning("[Scheduler] Sin chat configurado: mandá /start al bot.")
        return
    tomorrow = date.today() + timedelta(days=1)
    excursions = db.get_excursions_for_date(tomorrow)
    messages = build_guide_messages(excursions) or [
        f"✅ No hay guías que notificar mañana ({tomorrow.strftime('%d/%m/%Y')})."]
    try:
        for msg in messages:
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
        logger.info(f"[Scheduler] Mensajes para guías enviados a {chat_id}.")
    except Exception as e:
        logger.error(f"[Scheduler] No pude enviar los mensajes para guías a {chat_id}: {e}")


SCHEDULER = None      # referencia al scheduler activo, para el comando /avisos


def setup_scheduler(bot) -> AsyncIOScheduler:
    global SCHEDULER
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
    SCHEDULER = scheduler
    return scheduler
