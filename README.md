# Bot de Logística — Turismo Aventura Bariloche

Bot de Telegram que genera planillas Excel para excursiones, agrega eventos a Google Calendar y envía recordatorios automáticos.

---

## Lo que hace

- **Generación de planillas**: escribís en Telegram y te manda el Excel al instante
- **Google Calendar**: cada excursión registrada aparece en tu calendario
- **11:00 hs**: te manda el resumen de gastronomía para las salidas del día siguiente
- **16:00 hs**: te manda el mensaje para reenviarle al guía por WhatsApp

---

## Ejemplos de pedidos

```
Planilla kayak mascardi 4 pax 14/4 guía Julián
Plani fd kayak tres reyes 6 pax 20/4, guia rodri, 2 vegetarianos
Kayak mascardi 3 pax el 2 de abril, guía Julián Donatelli, una celíaca
```

---

## Setup (una sola vez)

### Paso 1 — Crear el bot de Telegram

1. Abrí Telegram y buscá **@BotFather**
2. Escribí `/newbot`
3. Elegí un nombre (ej: "Logística Kayak BA") y un username (ej: `kayak_ba_bot`)
4. BotFather te da un **token** — guardalo, lo vas a necesitar

### Paso 2 — Subir el código a GitHub

1. Creá una cuenta en [github.com](https://github.com) si no tenés
2. Creá un repositorio nuevo (botón verde "New")
3. Subí todos los archivos de esta carpeta al repositorio

### Paso 3 — Deploy en Railway

1. Creá cuenta en [railway.app](https://railway.app) (gratis)
2. Hacé clic en **"New Project"** → **"Deploy from GitHub repo"**
3. Seleccioná tu repositorio
4. En **Variables**, agregá:
   - `TELEGRAM_TOKEN` = el token de BotFather
   - `TELEGRAM_OWNER_ID` = (por ahora dejalo vacío, lo completás en el Paso 5)
5. Hacé clic en **Deploy**

### Paso 4 — Obtener tu chat ID

1. Abrí Telegram y buscá tu bot por su username
2. Enviá `/start`
3. En Railway, revisá los **Logs** — vas a ver tu chat_id en el mensaje de inicio
4. Volvé a Variables en Railway, agregá `TELEGRAM_OWNER_ID` con ese número
5. Hacé **Redeploy**

### Paso 5 — Google Calendar (opcional, podés hacerlo después)

1. Entrá a [console.cloud.google.com](https://console.cloud.google.com)
2. Creá un proyecto nuevo (botón arriba a la izquierda)
3. Buscá **"Google Calendar API"** y habilitala
4. Andá a **"Credenciales"** → **"Crear credenciales"** → **"Cuenta de servicio"**
5. Poné cualquier nombre, creá la cuenta
6. Hacé clic en la cuenta creada → **"Claves"** → **"Agregar clave"** → **JSON**
7. Se descarga un archivo JSON — ese es `google_credentials.json`
8. En tu Google Calendar, compartí el calendario con el email de la cuenta de servicio
   (lo encontrás dentro del JSON, campo `client_email`), con permiso de **editar**
9. En Railway, subí el archivo JSON como variable o como archivo en el proyecto
10. Agregá la variable `GOOGLE_CALENDAR_ID=primary`

---

## Comandos del bot

| Comando | Qué hace |
|---------|----------|
| `/start` | Activa el bot y registra tu cuenta |
| `/proximas` | Lista las excursiones de los próximos 7 días |
| `/gastro` | Muestra el resumen de gastronomía de mañana |
| `/guias` | Muestra los mensajes para reenviar a los guías |

---

## Agregar nuevas actividades

Editá `parser.py` y agregá la actividad en el bloque `# Actividad`.
Para agregar sitios nuevos, agregá el nombre en el diccionario `SITES`.
