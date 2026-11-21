"""
Interpretación de mensajes con IA (Claude).

Convierte un mensaje libre ("mañana tronador 5 pax con rodri, uno celíaco")
en los mismos datos que produce parser.py, así el resto del bot no cambia.

- Si no está configurada ANTHROPIC_API_KEY, o la IA falla, devuelve None
  y bot.py usa el parser de reglas de siempre como respaldo.
- El catálogo de actividades sale de generator.TEMPLATES: cuando se agrega
  una planilla nueva al generador, la IA la reconoce automáticamente.
"""
import os
import json
import logging
from datetime import date, timedelta

import generator
import parser as rules_parser

logger = logging.getLogger(__name__)

MODEL = os.environ.get('ANTHROPIC_MODEL', 'claude-haiku-5-5')
API_KEY = os.environ.get('ANTHROPIC_API_KEY')

try:
    import anthropic
    _client = anthropic.Anthropic(api_key=API_KEY, timeout=20.0) if API_KEY else None
except ImportError:
    _client = None

DAY_NAMES = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']

UPDATE_ACTIONS = [
    'cancel', 'update_hora', 'update_guide', 'update_date', 'update_site',
    'update_pax', 'update_hotel', 'update_agency', 'update_driver', 'update_wetsuit', 'update_client',
    'update_personal',
    'update_restrictions', 'set_restrictions', 'edit_item',
    'add_extra', 'remove_extra',
    'resend_planilla', 'reset_planilla',
]


def available() -> bool:
    return _client is not None


# ── Herramienta que la IA "completa" (salida estructurada) ────────────────────

def _tool_schema() -> dict:
    activities = list(generator.TEMPLATES.keys())
    return {
        'name': 'registrar_interpretacion',
        'description': 'Devuelve la interpretación estructurada del mensaje del usuario.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'intent': {
                    'type': 'string',
                    'enum': ['create', 'create_batch', 'query', 'update', 'unknown'],
                    'description': (
                        'create = pedido de planilla/salida nueva (o completar/corregir el borrador pendiente); '
                        'create_batch = VARIAS salidas en el mismo mensaje (una por línea o enumeradas); '
                        'query = consulta de qué salidas hay en una fecha; '
                        'update = modificar, cancelar o reenviar la planilla de una salida YA registrada; '
                        'unknown = no se entiende o no tiene que ver con el bot.'
                    ),
                },
                # ---- create ----
                'activity': {'type': 'string', 'enum': activities,
                             'description': 'Modelo de salida del catálogo.'},
                'site': {'type': 'string', 'description': 'Lugar, con el nombre del catálogo si coincide.'},
                'pax': {'type': 'integer'},
                'date': {'type': 'string', 'description': 'Fecha de la salida, YYYY-MM-DD.'},
                'guide': {'type': 'string', 'description': 'Nombre del guía, con mayúscula inicial.'},
                'client': {'type': 'string', 'description': 'Nombre de la reserva / cliente.'},
                'hotel': {'type': 'string', 'description': 'Hotel de pickup.'},
                'agency': {'type': 'string', 'description': 'Agencia o cliente corporativo que vende la salida (Say Hueque, GFT, Beyond BA…). No confundir con el nombre del pasajero.'},
                'driver': {'type': 'string', 'description': 'Conductor o móvil ("Pablo", "SP 01", "H1").'},
                'personal': {'type': 'integer', 'description': 'Cuánta gente de la empresa va ("2 perso", "+1 personal").'},
                'wetsuit': {'type': 'string', 'description': 'Talles de botitas de neoprene, formato "38, 40, 42" o "2x40, 1x43".'},
                'hora': {'type': 'string', 'description': 'Hora de retiro, formato "H:MM hs" (ej "9:30 hs").'},
                'dietary_restrictions': {'type': 'string',
                                         'description': 'Formato: "2x vegetariano/a, 1x celíaco/a (sin TACC)".'},
                'extras': {'type': 'array', 'items': {'type': 'string', 'enum': ['infusiones', 'sopa']},
                           'description': ('Extras para días fríos: infusiones = set de té/café (también si dicen '
                                           '"hace frío"); sopa = sopa de calabaza. En create, o en add_extra/remove_extra.')},
                'salidas': {
                    'type': 'array',
                    'description': 'Solo para create_batch: una entrada por salida, con los mismos campos que create.',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'activity': {'type': 'string', 'enum': activities},
                            'site': {'type': 'string'}, 'pax': {'type': 'integer'},
                            'date': {'type': 'string'}, 'guide': {'type': 'string'},
                            'client': {'type': 'string'}, 'agency': {'type': 'string'},
                            'hotel': {'type': 'string'}, 'hora': {'type': 'string'},
                            'driver': {'type': 'string'}, 'wetsuit': {'type': 'string'},
                            'personal': {'type': 'integer'},
                            'dietary_restrictions': {'type': 'string'},
                            'extras': {'type': 'array', 'items': {'type': 'string', 'enum': ['infusiones', 'sopa']}},
                        },
                    },
                },
                # ---- query ----
                'query_date': {'type': 'string', 'description': 'Fecha consultada, YYYY-MM-DD.'},
                # ---- update ----
                'action': {'type': 'string', 'enum': UPDATE_ACTIONS},
                'target_date': {'type': 'string',
                                'description': 'Fecha ACTUAL de la salida a modificar, YYYY-MM-DD.'},
                'identifier': {'type': 'string', 'description': 'Nombre del guía o de la reserva que identifica la salida.'},
                'identifier_type': {'type': 'string', 'enum': ['guide', 'client']},
                'item_op': {'type': 'string', 'enum': ['set', 'add', 'remove'],
                            'description': 'Solo para edit_item: set=poner cantidad, add=sumar, remove=sacar.'},
                'item': {'type': 'string', 'description': 'Solo para edit_item: nombre del ítem de la planilla (ej "vino", "termos").'},
                'quantity': {'type': 'string', 'description': 'Solo para edit_item: cantidad (número, "varios" o "/").'},
                'new_value': {'type': 'string', 'description': (
                    'Valor nuevo. hora: "H:MM hs"; fecha: YYYY-MM-DD; pax: número; '
                    'restricciones: SOLO las que se agregan, mismo formato que dietary_restrictions.')},
                # ---- unknown ----
                'reply': {'type': 'string',
                          'description': 'Solo si intent=unknown: respuesta breve al usuario, en español rioplatense.'},
            },
            'required': ['intent'],
        },
    }


def _system_prompt(today: date, upcoming: list, pending: dict | None) -> str:
    calendario = '\n'.join(
        f"- {DAY_NAMES[(today + timedelta(days=i)).weekday()]} "
        f"{(today + timedelta(days=i)).isoformat()}"
        + (' (hoy)' if i == 0 else ' (mañana)' if i == 1 else '')
        for i in range(15)
    )
    actividades = '\n'.join(
        f"- {name}: {tmpl.get('gastronomy_title', '')}" for name, tmpl in generator.TEMPLATES.items()
    )
    alias = ', '.join(f'"{k}" → {v}' for k, v in generator.ACTIVITY_ALIASES.items())
    sitios = ', '.join(sorted(set(rules_parser.SITES.values())))

    if upcoming:
        salidas = '\n'.join(
            f"- {e['date']} | {e.get('activity')} | {e.get('site') or '-'} | {e.get('pax')} pax | "
            f"guía {e.get('guide') or '-'} | reserva {e.get('client') or '-'} | hora {e.get('hora') or '-'}"
            for e in upcoming
        )
    else:
        salidas = '(ninguna)'

    borrador = json.dumps(pending, ensure_ascii=False, default=str) if pending else '(ninguno)'

    return f"""Sos el intérprete de un bot de Telegram de logística de una empresa de turismo aventura en Bariloche.
Tu única tarea es convertir el mensaje del usuario en datos llamando a la herramienta registrar_interpretacion.
No inventes datos: si algo no está en el mensaje (ni en el borrador pendiente), dejalo vacío.

HOY: {DAY_NAMES[today.weekday()]} {today.isoformat()}. Calendario de referencia:
{calendario}
Fechas tipo "20/6" son día/mes. Si no dicen el año, usá la próxima vez que ocurra esa fecha (nunca una fecha pasada).

MODELOS DE SALIDA (catálogo, usá exactamente estos nombres):
{actividades}
Alias habituales: {alias}
Reglas: "kayak" sin más → FD Kayak. "HD", "half day" o "medio día" con kayak → HD Kayak.
"navegación" con almuerzo/privada/pvt → Navegacion AC; si no, Navegacion Regular.
"Valle Encantado": con asado → Valle Asado; pollo/pollo al disco → Valle Encantado Pollo; trucha → Valle Encantado Trucha.
Si dicen solo "Valle Encantado" sin la comida, dejá activity vacío (el bot va a preguntar).
"Kayak VLA" / "kayak Villa La Angostura" → FD Kayak con site "Villa La Angostura".

SITIOS CONOCIDOS: {sitios}. Si mencionan otro lugar, usalo tal cual con mayúscula inicial.

SALIDAS YA REGISTRADAS (próximos días), para resolver modificaciones:
{salidas}
Si piden modificar una salida sin decir la fecha, usá esta lista para deducir target_date e identifier.
Para update_date: target_date = fecha actual, new_value = fecha nueva.
Para update_restrictions: new_value contiene solo lo que se agrega.
"Reenviame / mandame de nuevo la planilla de ..." = update con action resend_planilla.
"Volvé a la planilla original/automática de ..." = update con action reset_planilla.
Cambiar un ítem de la planilla ("poné 4 vinos", "agregá 2 termos", "sacá las polainas") = action edit_item
con item_op, item y quantity. Reemplazar TODAS las restricciones ("las restricciones son…", "sin restricciones")
= action set_restrictions con new_value (usar "Ninguna" si no hay).
Sumar o sacar el set de infusiones/café o la sopa de calabaza a una salida ya registrada
= action add_extra / remove_extra con extras.

BORRADOR PENDIENTE de este usuario (planilla nueva aún no confirmada):
{borrador}
Si el mensaje trae VARIAS salidas (una por línea, o numeradas), usá intent=create_batch
y poné cada una en salidas, repartiendo los datos comunes (fecha, agencia) a todas.

Si el mensaje completa o corrige ese borrador ("son 5", "el guía es Rodri", "cambialo al 21"),
devolvé intent=create con TODOS los datos del borrador combinados con la corrección.

client es el NOMBRE del pasajero o de la reserva. agency es la agencia o empresa que la vende.
Si dicen "cliente Say Hueque" eso es agency; "reserva Johnson" o "a nombre de Johnson" es client.

Restricciones alimentarias: formato "Nx descripción", separadas por coma.
Ej: "2x vegetariano/a, 1x celíaco/a (sin TACC), 1x vegano/a, alergia frutos secos".
"""


# ── Conversión al formato que espera bot.py ───────────────────────────────────

def _to_date(val):
    if not val:
        return None
    try:
        return date.fromisoformat(str(val)[:10])
    except ValueError:
        return None


def _gastro_type(activity: str) -> str:
    return 'snacks' if activity == 'HD Kayak' else 'AC'


def _datos_create(out: dict) -> dict:
    """Pasa la salida de la IA al formato que usa el resto del bot."""
    activity = out.get('activity')
    return {
        'activity': activity,
        'gastronomy_type': _gastro_type(activity) if activity else 'AC',
        'site': out.get('site'),
        'pax': out.get('pax'),
        'date': _to_date(out.get('date')),
        'client': out.get('client'),
        'guide': out.get('guide'),
        'hora': out.get('hora'),
        'hotel': out.get('hotel'),
        'agency': out.get('agency'),
        'driver': out.get('driver'),
        'wetsuit': out.get('wetsuit'),
        'dietary_restrictions': out.get('dietary_restrictions'),
        'extras': [e for e in (out.get('extras') or []) if e in ('infusiones', 'sopa')],
    }


def interpret(text: str, upcoming: list | None = None, pending: dict | None = None,
              today: date | None = None) -> dict | None:
    """
    Devuelve:
      {'intent': 'create', 'data': {...formato de parser.parse_message...}}
      {'intent': 'query',  'date': date}
      {'intent': 'update', 'data': {...formato de parser.parse_update...}}
      {'intent': 'unknown', 'reply': str}
    o None si la IA no está disponible o falló (→ usar parser de reglas).
    """
    if not _client:
        return None
    today = today or date.today()

    try:
        resp = _client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=_system_prompt(today, upcoming or [], pending),
            tools=[_tool_schema()],
            tool_choice={'type': 'tool', 'name': 'registrar_interpretacion'},
            messages=[{'role': 'user', 'content': text}],
        )
        block = next(b for b in resp.content if b.type == 'tool_use')
        out = dict(block.input)
    except Exception as e:
        logger.error(f"[IA] Error interpretando mensaje: {e}")
        return None

    logger.info(f"[IA] {text!r} → {out}")
    intent = out.get('intent')

    if intent == 'create_batch':
        salidas = [_datos_create(x) for x in (out.get('salidas') or [])]
        salidas = [x for x in salidas if x.get('activity') or x.get('pax')]
        if len(salidas) >= 2:
            return {'intent': 'create_batch', 'data': salidas}
        if salidas:
            return {'intent': 'create', 'data': salidas[0]}
        return None

    if intent == 'create':
        return {'intent': 'create', 'data': _datos_create(out)}

    if intent == 'query':
        d = _to_date(out.get('query_date'))
        return {'intent': 'query', 'date': d} if d else None

    if intent == 'update':
        action = out.get('action')
        target = _to_date(out.get('target_date'))
        if action not in UPDATE_ACTIONS or not target:
            return None
        new_value = out.get('new_value')
        if action == 'update_date':
            new_value = _to_date(new_value)
        elif action in ('add_extra', 'remove_extra'):
            new_value = [e for e in (out.get('extras') or []) if e in ('infusiones', 'sopa')]
        elif action == 'edit_item':
            new_value = {'op': out.get('item_op') or 'set', 'item': out.get('item'), 'qty': out.get('quantity')}
        elif action in ('update_pax', 'update_personal'):
            try:
                new_value = int(new_value)
            except (TypeError, ValueError):
                new_value = None
        data = {
            'action': action,
            'date': target,
            'identifier': out.get('identifier'),
            'identifier_type': out.get('identifier_type') or ('guide' if out.get('identifier') else None),
            'new_value': new_value,
        }
        return {'intent': 'update', 'data': data}

    return {'intent': 'unknown', 'reply': out.get('reply') or ''}
