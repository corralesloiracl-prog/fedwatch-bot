#!/usr/bin/env python3
"""
Monitor de probabilidades de tipos de la Fed (metodología CME FedWatch)
con avisos por Telegram solo cuando cambian.

Cálculo (igual que FedWatch):
  - Tipo antes de la reunión = EFFR actual (NY Fed).
  - Tipo esperado después    = 100 - precio del futuro Fed Funds (ZQ) del mes
                               siguiente a la reunión (noviembre no tiene reunión).
  - La diferencia se reparte entre los dos escenarios de 25 pb más cercanos.

Variables de entorno:
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID  -> obligatorias para enviar avisos
  THRESHOLD_PP  (defecto 1.0)       -> cambio mínimo, en puntos %, para avisar
  STATE_FILE    (defecto state.json)

Uso:
  python fedwatch_monitor.py          # una comprobación (GitHub Actions / cron)
  python fedwatch_monitor.py --test   # manda el estado actual aunque no cambie
  python fedwatch_monitor.py --loop   # bucle cada 15 min (para tu PC / VPS)
"""
import calendar
import datetime as dt
import json
import math
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# ---------------- CONFIGURACIÓN ----------------
MEETING = dt.date(2026, 10, 28)          # día de la decisión (14:00 ET = 19:00 Madrid)
MEETING_LABEL = "FOMC 27-28 oct 2026"
THRESHOLD_PP = float(os.getenv("THRESHOLD_PP", "1.0"))
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
LOOP_MINUTES = 15
# -----------------------------------------------

MONTH_CODES = "FGHJKMNQUVXZ"
MADRID = ZoneInfo("Europe/Madrid")


def zq_ticker(year: int, month: int) -> str:
    return f"ZQ{MONTH_CODES[month - 1]}{str(year)[-2:]}.CBT"


def next_month(d: dt.date) -> tuple[int, int]:
    return (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)


def last_price(ticker: str) -> float:
    import yfinance as yf

    t = yf.Ticker(ticker)
    for period, interval in (("5d", "15m"), ("1mo", "1d")):
        hist = t.history(period=period, interval=interval)
        closes = hist["Close"].dropna() if not hist.empty else []
        if len(closes):
            return float(closes.iloc[-1])
    raise RuntimeError(f"Sin precio para {ticker}")


def get_effr() -> dict:
    url = "https://markets.newyorkfed.org/api/rates/unsecured/effr/last/1.json"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    d = r.json()["refRates"][0]
    return {
        "effr": float(d["percentRate"]),
        "lo": float(d["targetRateFrom"]),
        "hi": float(d["targetRateTo"]),
        "date": d["effectiveDate"],
    }


def post_meeting_rate(effr: float) -> tuple[float, str]:
    """Tipo implícito tras la reunión. Usa el mes siguiente; si falla, el mes de la reunión."""
    y, m = next_month(MEETING)
    tk = zq_ticker(y, m)
    try:
        price = last_price(tk)
        return 100 - price, f"{tk} {price:.4f}"
    except Exception:
        tk = zq_ticker(MEETING.year, MEETING.month)
        price = last_price(tk)
        days = calendar.monthrange(MEETING.year, MEETING.month)[1]
        d_before = MEETING.day                 # el nuevo tipo aplica desde el día siguiente
        d_after = days - d_before
        avg = 100 - price
        return (avg * days - effr * d_before) / d_after, f"{tk} {price:.4f}"


def probabilities(effr: float, post: float, lo: float, hi: float) -> dict[str, float]:
    steps = (post - effr) * 100 / 25
    k = math.floor(steps)
    p_up = steps - k
    out = {}
    for n, p in ((k, 1 - p_up), (k + 1, p_up)):
        if p < 0.0005:
            continue
        label = f"{lo + n*0.25:.2f}-{hi + n*0.25:.2f}%"
        if n == 0:
            label += " (mantener)"
        else:
            label += f" ({'subida' if n > 0 else 'bajada'} {abs(n)*25} pb)"
        out[label] = round(p * 100, 1)
    return out


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def send_telegram(text: str) -> None:
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[sin Telegram configurado]\n" + text)
        return
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": text},
        timeout=20,
    )
    r.raise_for_status()


def build_message(probs, prev, info, src, first) -> str:
    now = dt.datetime.now(MADRID).strftime("%d/%m %H:%M")
    head = "🟢 Monitor activado" if first else "📊 Cambio en probabilidades Fed"
    lines = [f"{head} — {MEETING_LABEL}", ""]
    for label, p in sorted(probs.items()):
        if first or label not in prev:
            lines.append(f"{label}: {p:.1f}%")
        else:
            d = p - prev[label]
            arrow = "▲" if d > 0 else "▼" if d < 0 else "="
            lines.append(f"{label}: {p:.1f}%  ({arrow}{abs(d):.1f})")
    for label in prev:
        if label not in probs:
            lines.append(f"{label}: 0.0%  (antes {prev[label]:.1f}%)")
    lines += ["", f"EFFR {info['effr']:.2f}% | {src}", f"🕒 {now} (Madrid)"]
    return "\n".join(lines)


def changed(probs: dict, prev: dict) -> bool:
    keys = set(probs) | set(prev)
    return any(abs(probs.get(k, 0) - prev.get(k, 0)) >= THRESHOLD_PP for k in keys)


def check(force: bool = False) -> None:
    if dt.date.today() > MEETING:
        print("La reunión ya pasó. Actualiza MEETING en el script.")
        return
    info = get_effr()
    post, src = post_meeting_rate(info["effr"])
    probs = probabilities(info["effr"], post, info["lo"], info["hi"])
    state = load_state()
    prev = state.get("probs", {})
    first = not prev or state.get("meeting") != MEETING.isoformat()
    print(dt.datetime.now(MADRID).isoformat(timespec="minutes"), probs)
    if force or first or changed(probs, prev):
        send_telegram(build_message(probs, {} if first else prev, info, src, first))
        save_state({"meeting": MEETING.isoformat(), "probs": probs,
                    "sent_at": dt.datetime.now(MADRID).isoformat(timespec="minutes")})


if __name__ == "__main__":
    if "--loop" in sys.argv:
        while True:
            try:
                check()
            except Exception as e:
                print("Error:", e)
            time.sleep(LOOP_MINUTES * 60)
    else:
        check(force="--test" in sys.argv)
