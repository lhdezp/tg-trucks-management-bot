# Gestion de camiones (bot de Telegram)

Bot privado para administrar una flota de camiones desde Telegram. Permite registrar
viajes, camiones, conductores y tickets con imagen, y generar reportes semanales en
Excel por camion o generales.

Solo los IDs incluidos en `ADMIN_IDS` pueden usar el bot.

## Requisitos

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- Un bot creado con [@BotFather](https://t.me/BotFather)

## Configuracion

1. Copia `.env.example` a `.env`.
2. Completa `BOT_TOKEN` con el token de BotFather.
3. Completa `ADMIN_IDS` con los IDs de Telegram de los administradores,
   separados por comas.
4. Ajusta `TIMEZONE`, `CURRENCY` y `WEIGHT_UNIT` si hace falta.
5. Opcional: completa `GEMINI_API_KEY` con una clave de Google AI Studio para
   leer automaticamente el monto total de cada ticket con Gemini.

Las fechas, las semanas y el reporte automatico usan la zona horaria configurada.
La base de datos SQLite se crea automaticamente en `DB_PATH`.

## Ejecucion

```powershell
uv sync
uv run python main.py
```

## Uso

Todo se puede hacer con los botones del menu. Los comandos quedan disponibles como
atajos:

| Comando | Accion |
| --- | --- |
| `/start` | Inicio |
| `/menu` | Menu principal |
| `/viajes` | Lista de viajes |
| `/nuevoviaje` | Registrar un viaje |
| `/camiones` | Administrar camiones |
| `/conductores` | Administrar conductores |
| `/tickets` | Administrar los tickets de un viaje |
| `/semana` | Resumen de texto de la semana actual |
| `/reporte` | Excel general de la semana actual |
| `/reporte DD/MM/AAAA` | Excel de la semana de esa fecha |
| `/configuracion` | Reporte automatico |
| `/ayuda` | Ayuda |
| `/cancelar` | Cancelar el paso actual |

### Viajes

Cada viaje guarda camion, conductor, origen, destino, distancia en millas, duracion,
peso de la carga, porcentaje del conductor, pago de la carga, fecha, estado y notas.
El pago del conductor se calcula como `pago de la carga * porcentaje / 100`.

Un viaje puede estar en curso o finalizado. Se puede editar, cambiar de estado,
eliminar y adjuntar tickets.

### Tickets

Los tickets son imagenes. El bot guarda el identificador de Telegram de cada imagen
en lugar de descargarla de forma permanente, y permite reenviarlas al chat cuando
haga falta. Se pueden clasificar como gasolina, mantenimiento u otro.

Si `GEMINI_API_KEY` esta configurada, el bot descarga la imagen temporalmente y usa
Gemini para leer el monto total del ticket. El monto se puede corregir manualmente o
volver a analizar desde la opcion de montos. Los gastos de tickets se restan de la
ganancia neta del viaje:

`ganancia neta = pago de la carga - pago del conductor - gastos de tickets`

### Reportes

Los reportes cubren siempre de lunes a domingo. Se pueden generar:

- Para todos los camiones (general, agrupado por camion).
- Para un camion especifico.

Cada archivo Excel tiene tres hojas: `Finalizados`, `En curso` y `Ambos`. Incluye
gastos de tickets y ganancia neta por viaje, y marca los tickets que todavia no
tienen monto. El archivo se envia al chat y se elimina del servidor despues del envio.

### Reporte automatico

En `/configuracion` se puede cambiar el dia, la hora, el alcance, el destino y el
estado del reporte automatico. Por defecto se envia los domingos a las 09:00 al
chat configurado o, si no hay uno, a los administradores como respaldo. Si el bot
estuvo apagado a la hora programada, no se envia un reporte atrasado.
