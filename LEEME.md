# Bot FedWatch → Telegram

Cada 15 min calcula las probabilidades de la reunión de la Fed (27-28 oct 2026)
y te manda un Telegram **solo si alguna cambia ≥ 1 punto %**.

## 1. Crear el bot de Telegram (2 min)
1. En Telegram abre **@BotFather** → `/newbot` → ponle nombre. Te da un **token**.
2. Escribe cualquier cosa a tu bot nuevo.
3. Abre en el navegador `https://api.telegram.org/bot<TOKEN>/getUpdates`
   y copia el número de `"chat":{"id": ...}` → ese es tu **chat id**.

## 2. Subirlo a GitHub (gratis, sin tener el PC encendido)
1. Crea una cuenta en github.com y un repositorio nuevo **público**
   (en público los minutos de Actions son ilimitados; el token va en secretos, no se ve).
2. Sube estos archivos respetando la carpeta `.github/workflows/`.
3. Settings → Secrets and variables → Actions → **New repository secret**:
   - `TELEGRAM_TOKEN` = token de BotFather
   - `TELEGRAM_CHAT_ID` = tu chat id
4. Pestaña **Actions** → "FedWatch monitor" → **Run workflow**.
   Te llegará "🟢 Monitor activado" con las probabilidades actuales.

## Ajustes
- **Sensibilidad**: `THRESHOLD_PP` en `monitor.yml` (1.0 = avisa si cambia ≥1 punto).
- **Frecuencia**: la línea `cron` (`*/30 * * * *` = cada 30 min).
- **Otra reunión**: cambia `MEETING` y `MEETING_LABEL` al principio del script.
  Tras el 28 oct el script se para solo hasta que lo actualices.

## Alternativa: en tu PC
```
pip install requests yfinance
set TELEGRAM_TOKEN=...      (Windows)   /   export TELEGRAM_TOKEN=... (Mac/Linux)
set TELEGRAM_CHAT_ID=...
python fedwatch_monitor.py --loop
```
