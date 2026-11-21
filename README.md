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
9. En Railway, creá la variable `GOOGLE_CREDENTIALS_JSON` y pegá adentro **todo el contenido** del archivo JSON
10. Agregá la variable `GOOGLE_CALENDAR_ID` con el ID de tu calendario (o `primary`)
11. (Opcional, Drive) Agregá `GOOGLE_DRIVE_FOLDER_ID` con el ID de la carpeta donde guardar las planillas,
    y compartí esa carpeta con el `client_email` con permiso de editor
12. Probá con `/testcal` y `/testdrive` en el bot

### Paso 6 — Que no se borren los datos (importante)

Railway borra los archivos en cada redeploy, salvo que estén en un **volumen**.

1. En Railway, abrí el servicio del bot → clic derecho (o menú ⋯) → **Attach Volume**
2. Mount path: `/data`
3. En Variables, agregá `DB_PATH=/data/excursions.db`
4. Redeploy

### Paso 7 — Activar la IA (opcional, recomendado)

El bot entiende la mayoría de los pedidos con reglas propias (gratis). La IA solo se usa
cuando el mensaje es raro o ambiguo (en las pruebas, ~1 de cada 10 mensajes).
Sin la clave, el bot funciona igual: solo te va a pedir más aclaraciones.

1. Entrá a [platform.claude.com](https://platform.claude.com) y creá una cuenta
   (es distinta de tu cuenta de Claude; la facturación también es aparte)
2. Cargá crédito en **Billing** (prepago; con el crédito mínimo te alcanza para mucho tiempo)
3. Andá a **Settings → API keys** → **Create key**, ponele un nombre (ej: `bot-logistica`)
4. **Copiá la clave** (empieza con `sk-ant-`). Se muestra una sola vez; si la perdés, creás otra
5. En Railway → tu servicio → **Variables** → **New Variable**:
   `ANTHROPIC_API_KEY` = la clave
6. Railway redeploya solo. En **Logs** tiene que aparecer: `Interpretación con IA: activada`
7. En Telegram, `/uso` muestra cuántos mensajes usaron IA en el mes y el costo estimado

No compartas la clave ni la pegues en el código o en GitHub: va solo en las Variables de Railway.

### Paso 8 — Planilla DESPACHOS (opcional)

El bot puede anotar cada reserva en la planilla DESPACHOS de Drive.

1. En Google Cloud, habilitá también la **Google Sheets API**
2. Compartí la planilla con la cuenta del bot (el comando `/cuenta` te dice cuál es), con permiso de **Editor**
3. En Railway agregá `DESPACHOS_SHEET_ID` con el id de la planilla
   (lo sacás del link: `docs.google.com/spreadsheets/d/<ESTO>/edit`; también podés pegar el link entero)
4. Probá con `/testdespachos`

### Paso 9 — Planilla de Backroads (opcional)

El bot completa los pasajeros, el personal y las dietas de los servicios ya cargados,
y manda la reconfirmación de los de mañana todos los días a las 10:45.

1. Compartí la planilla con la cuenta del bot (`/cuenta`), permiso de **Editor**
2. En Railway agregá `BACKROADS_SHEET_ID` (podés pegar el link entero)
3. Probá con `/testbackroads`

Para completar un servicio, escribile al bot:
`Backroads Multi Adventure del 9/12, 12 pax, 2 perso, 2 veggie y 1 vegan`

### Paso 10 — Usarlo entre varias personas

1. Creá un grupo de Telegram con las personas del equipo y agregá el bot
2. En @BotFather: `/mybots` → tu bot → **Bot Settings** → **Group Privacy** → **Turn off**
   (si no, el bot no lee los mensajes normales del grupo)
3. Mandá `/start` **en el grupo**: los avisos de las 11 y las 16 van a llegar ahí

---

## Comandos del bot

| Comando | Qué hace |
|---------|----------|
| `/start` | Activa el bot y registra tu cuenta |
| `/proximas` | Lista las excursiones de los próximos 7 días |
| `/gastro` | Muestra el resumen de gastronomía de mañana |
| `/guias` | Muestra los mensajes para reenviar a los guías |
| `/uso` | Mensajes interpretados por reglas vs IA en el mes |

---

## Agregar nuevas actividades

Editá `parser.py` y agregá la actividad en el bloque `# Actividad`.
Para agregar sitios nuevos, agregá el nombre en el diccionario `SITES`.
