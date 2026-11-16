# Guía rápida: conseguir las credenciales de Google Drive

Esta guía es para una persona **sin conocimientos técnicos**. Explica, paso a paso y con enlaces, cómo conseguir los datos que el bot necesita para guardar los reportes (Excel) en tu Google Drive.

Al final vas a tener **4 datos** listos para pegar en un archivo de configuración:

1. `GOOGLE_OAUTH_CLIENT_ID`
2. `GOOGLE_OAUTH_CLIENT_SECRET`
3. `GOOGLE_OAUTH_REFRESH_TOKEN`
4. `GOOGLE_DRIVE_FOLDER_ID`

---

## Antes de empezar

Vas a necesitar:

- Una cuenta de **Google (Gmail)** con acceso a Google Drive.
- Una computadora con navegador (Chrome, Edge, etc.).
- Tener a mano el programa del bot y quién lo instala (para el último paso).
- Unos **15 minutos**.

> 💡 No hace falta pagar nada. Todo lo de esta guía es gratuito.

---

## Parte 1 — Crear un "proyecto" y activar Google Drive

Un "proyecto" es como una carpeta de trabajo interna de Google. Es solo un paso previo.

1. Entrá a: **https://console.cloud.google.com/**
2. Iniciá sesión con tu cuenta de Google.
3. Arriba a la izquierda, tocá el selector de proyecto y elegí:
   - El proyecto que ya existe (se llama `modular-sorter-439413-a9`), **o**
   - **“Proyecto nuevo”**, ponele un nombre (ej. `Truck Bot`) y creálo.
4. Ahora activá el servicio de Drive:
   - Entrá a: **https://console.cloud.google.com/apis/library/drive.googleapis.com**
   - Tocá el botón azul **“Habilitar”** (*Enable*).
   - Esperá unos segundos a que diga “API habilitada”.

---

## Parte 2 — Configurar la pantalla de permiso

Esta pantalla es la que verás cuando el bot te pida autorización.

1. Entrá a: **https://console.cloud.google.com/auth/overview**
2. Si es la primera vez, tocá **“Comenzar”** (*Get started*).
3. Completá:
   - **Nombre de la app:** `Truck Bot` (o el nombre que quieras)
   - **Correo de asistencia:** tu email
   - **Correo del desarrollador:** tu email
4. En **“Tipo de usuario”** elegí **Externo** (*External*).
5. En la sección de **permisos / accesos** (puede llamarse *Data Access*), agregá este permiso y guardá:
   ```
   https://www.googleapis.com/auth/drive.file
   ```
6. En **“Usuarios de prueba”** (*Audience* / *Test users*), agregá tu propio email.
7. Por último, buscá el botón **“Publicar app”** (*Publish app*) y confirmá.
   - Verás un aviso de que la app “no está verificada”. Es **normal** para uso personal; no pasa nada.

> ⚠️ Importante: si **no** publicás la app y la dejás en estado “Prueba” (*Testing*), la autorización caduca **cada 7 días** y hay que repetir el paso de la Parte 4 seguido. Publicándola, dura indefinidamente.

---

## Parte 3 — Crear la “llave” (los 2 primeros datos)

Acá se generan el **ID de cliente** y la **clave secreta**.

1. Entrá a: **https://console.cloud.google.com/apis/credentials**
2. Arriba, tocá **“Crear credenciales”** (*Create credentials*) → **“ID de cliente de OAuth”**.
3. En **“Tipo de aplicación”** elegí **“Aplicación de escritorio”** (*Desktop app*).
4. En **“Nombre”** poné: `truck-bot-drive`.
5. Tocá **“Crear”**.
6. Aparece una ventana con dos botones. Tocá **“Descargar JSON”**.
7. Se te va a descargar un archivo (algo como `client_secret_123...json`).
   - **Renombralo a** `client_secret.json`.
   - **Ponelo en la carpeta principal del bot** (donde está el archivo `main.py`).

> Ese archivo ya contiene el `CLIENT_ID` y el `CLIENT_SECRET`. No hace falta abrirlo a mano; el siguiente paso los extrae solo.

---

## Parte 4 — Obtener el “token de actualización” (el 3er dato)

Este paso lo hace la persona que administra el bot, en la computadora donde está instalado. Es un comando corto.

1. Abrí una terminal (PowerShell) **en la carpeta del bot**.
2. Ejecutá:
   ```powershell
   uv run python scripts/get_drive_token.py
   ```
3. Se va a abrir el navegador automáticamente:
   - Iniciá sesión con la **misma cuenta de Google** de la Parte 1.
   - Aceptá los permisos.
   - Si aparece “Google no verificó esta app”, tocá **“Configuración avanzada”** → **“Continuar”**.
4. Cuando termines, la terminal va a mostrar algo así:
   ```
   GOOGLE_OAUTH_CLIENT_ID=...
   GOOGLE_OAUTH_CLIENT_SECRET=...
   GOOGLE_OAUTH_REFRESH_TOKEN=...
   ```
5. **Copiá esas tres líneas.** Ya tenés los 3 primeros datos.

---

## Parte 5 — Conseguir el ID de la carpeta (el 4to dato)

Este es el identificador de la carpeta de Drive donde se van a guardar los reportes.

1. Abrí Google Drive: **https://drive.google.com/**
2. Entrá a la carpeta donde querés los reportes (creala si no existe).
3. Mirá la dirección (URL) arriba en el navegador. Es algo así:
   ```
   https://drive.google.com/drive/folders/1NUpqybn8vLW_SKVrLw0yvDVv7b2hdKW-
   ```
4. El ID es **lo que está después de `/folders/`**, o sea:
   ```
   1NUpqybn8vLW_SKVrLw0yvDVv7b2hdKW-
   ```
5. Copiá ese texto. Ese es el `GOOGLE_DRIVE_FOLDER_ID`.

> 🚨 La carpeta tiene que ser **tuya** (o donde tengas permiso para crear archivos). Como ahora el bot guarda con **tu usuario**, los archivos quedan a tu nombre.

---

## Parte 6 — Pegar todo en el archivo de configuración

En la carpeta del bot hay un archivo llamado **`.env`**. Abrilo con un editor de texto (Bloc de notas) y buscá estas líneas. Completalas con lo que copiaste:

```env
GOOGLE_OAUTH_CLIENT_ID=   ← pegar el ID de cliente
GOOGLE_OAUTH_CLIENT_SECRET=   ← pegar la clave secreta
GOOGLE_OAUTH_REFRESH_TOKEN=   ← pegar el token de actualización
GOOGLE_DRIVE_FOLDER_ID=   ← pegar el ID de la carpeta
```

Guardá el archivo y reiniciá el bot.

---

## Resumen de los 4 datos

| Dato | De dónde sale |
|------|----------------|
| `GOOGLE_OAUTH_CLIENT_ID` | Lo imprime la terminal en la Parte 4 (también está en `client_secret.json`) |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Lo imprime la terminal en la Parte 4 (también está en `client_secret.json`) |
| `GOOGLE_OAUTH_REFRESH_TOKEN` | Lo imprime la terminal en la Parte 4 |
| `GOOGLE_DRIVE_FOLDER_ID` | La parte final de la URL de la carpeta en Drive (Parte 5) |

---

## Problemas frecuentes

- **“Google no verificó esta app”**: es normal. Tocá *Configuración avanzada* → *Ir a Truck Bot (no seguro)* → *Continuar*.
- **La autorización caduca cada 7 días**: la app quedó en estado “Prueba”. Volvé a la Parte 2 y tocá *Publicar app*.
- **Error de permisos al subir a la carpeta**: la carpeta no es tuya o no tenés permiso de edición. Probá creando una carpeta nueva desde tu propia cuenta.
- **No aparece el `refresh_token`**: puede que ya hayas autorizado antes. Entrá a **https://myaccount.google.com/permissions**, quitá el acceso de la app y repetí la Parte 4.
- **Querés revocar el acceso en cualquier momento**: entrá a **https://myaccount.google.com/permissions** y quitá el acceso de “Truck Bot”.
