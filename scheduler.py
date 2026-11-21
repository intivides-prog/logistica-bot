"""
Tareas programadas:
  11:00 hs → resumen de gastronomía para el día siguiente
  16:00 hs → mensaje para reenviar al guía
Zona horaria: America/Argentina/Buenos_Aires
"""
import asyncio
import os
import re
import logging
from datetime import datetime, date, timedelta
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
        guide = (ex.get('guide') or '').strip()
        if not guide:
            continue          # sin guía asignado: va en el aviso aparte, no se arma mensaje
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
    sin_guia = [e for e in excursions if not (e.get('guide') or '').strip()]
    if sin_guia:
        detalle = '\n'.join(
            f"• {e.get('activity') or '—'} — {e.get('pax') or '?'} pax"
            + (f" ({e['client']})" if e.get('client') else '')
            for e in sin_guia)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ *Mañana hay {len(sin_guia)} salida(s) sin guía asignado:*\n{detalle}",
                parse_mode='Markdown')
        except Exception as e:
            logger.error(f"[Scheduler] No pude avisar las salidas sin guía: {e}")

    messages = build_guide_messages(excursions) or [
        f"✅ No hay guías que notificar mañana ({tomorrow.strftime('%d/%m/%Y')})."]
    try:
        for msg in messages:
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
        logger.info(f"[Scheduler] Mensajes para guías enviados a {chat_id}.")
    except Exception as e:
        logger.error(f"[Scheduler] No pude enviar los mensajes para guías a {chat_id}: {e}")


SCHEDULER = None      # referencia al scheduler activo, para el comando /avisos

DIAS_SEMANA = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']


async def job_backroads(bot):
    """Reconfirmación de los servicios de Backroads de mañana."""
    import sheets_service
    logger.info("[Scheduler] Reconfirmación de Backroads.")
    if not sheets_service.backroads_disponible():
        return
    chat_id = _notify_chat_id()
    if not chat_id:
        logger.warning("[Scheduler] Sin chat configurado para Backroads.")
        return
    manana = date.today() + timedelta(days=1)
    try:
        texto = await asyncio.get_event_loop().run_in_executor(
            None, lambda: sheets_service.backroads_reconfirmacion(manana))
        if not texto:
            return          # sin servicios ese día: no se manda nada
        await bot.send_message(chat_id=chat_id, text=texto, parse_mode='Markdown')
        logger.info("[Scheduler] Backroads enviado.")
    except Exception as e:
        logger.error(f"[Scheduler] No pude mandar la reconfirmación de Backroads: {e}")


async def job_backup_db(bot):
    """
    Copia la base a Google Drive una vez por día. Se guarda una copia por día
    de la semana, así siempre hay siete versiones para atrás sin que crezca.
    """
    import shutil
    import tempfile
    import drive_service

    logger.info("[Scheduler] Backup diario de la base.")
    if not os.path.exists(db.DB_PATH):
        logger.warning("[Backup] No encontré la base en %s", db.DB_PATH)
        return
    dia = DIAS_SEMANA[datetime.now(TZ).weekday()]
    nombre = f"backup-bot-{dia}.db"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            copia = os.path.join(tmp, nombre)
            # copia consistente aunque el bot esté escribiendo
            with db.get_conn() as conn:
                destino = __import__('sqlite3').connect(copia)
                conn.backup(destino)
                destino.close()
            link = drive_service.upload_file(copia, nombre)
        if link:
            logger.info(f"[Backup] Subido a Drive: {nombre}")
        else:
            logger.error("[Backup] No se pudo subir a Drive (revisar carpeta y permisos).")
    except Exception as e:
        logger.error(f"[Backup] Error haciendo el backup: {e}")



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
    scheduler.add_job(
        lambda: asyncio.ensure_future(job_backroads(bot)),
        CronTrigger(hour=10, minute=45, timezone=TZ),
        id='backroads',
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: asyncio.ensure_future(job_backup_db(bot)),
        CronTrigger(hour=3, minute=30, timezone=TZ),
        id='backup_db',
        replace_existing=True,
    )

    scheduler.start()
    SCHEDULER = scheduler
    return scheduler
