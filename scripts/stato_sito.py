#!/usr/bin/env python3
"""
stato_sito.py — Lo stato di mull2five.it su Telegram, visto da fuori.

Lo lancia GitHub Actions ogni cinque minuti (.github/workflows/stato-sito.yml):
il sito non può dire da solo che è giù, se a cadere è Render o il contenitore.
Chiama /health e scrive su Telegram solo quando qualcosa cambia:

  🔴 non risponde — dopo tre tentativi, per non gridare a un singhiozzo
  🟠 risponde, ma il database no o lo schema è rimasto indietro
  🟢 di nuovo su (o di nuovo a posto), e dopo quanto
  🚀 in produzione un commit nuovo, con il suo titolo

Fra un giro e l'altro si ricorda com'era in un file (--stato), che il workflow
tiene nella cache di GitHub. Senza file è il primo giro: se va tutto bene non
dice niente. Prima manda, poi salva: se Telegram non risponde il workflow
fallisce, GitHub manda un'email, e il giro dopo ci riprova. Con --sempre (il
lancio a mano da GitHub) scrive lo stato anche se non è cambiato niente.

Solo libreria standard: sul runner non si installa niente.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

URL = "https://mull2five.it/health"
NAME = "mull2five.it"
ATTEMPTS = 3
PAUSE = 20.0       # secondi fra un tentativo e l'altro
TIMEOUT = 30       # Render può metterci un po' a rispondere dopo un deploy


def fetch(url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "mull2five-stato-sito"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — URL fisso, https
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def classify(status: int, body: str) -> dict:
    """Una risposta di /health: ok, degraded (risponde ma zoppica) o down."""
    if status != 200:
        return {"state": "down", "commit": None, "detail": f"HTTP {status}"}
    try:
        health = json.loads(body)
    except ValueError:
        return {"state": "down", "commit": None, "detail": "una risposta che non è JSON"}
    commit = health.get("commit")
    schema = health.get("schema") or {}
    if health.get("database") != "ok":
        detail = "il database non risponde"
    elif schema.get("indietro"):
        detail = f"lo schema è a {schema.get('applicata')} invece che a {schema.get('attesa')}"
    elif health.get("status") != "ok":
        detail = f"lo stato è {health.get('status')}"
    else:
        return {"state": "ok", "commit": commit, "detail": ""}
    return {"state": "degraded", "commit": commit, "detail": detail}


def check(
    url: str = URL,
    fetch: Callable[[str, float], tuple[int, str]] = fetch,
    attempts: int = ATTEMPTS,
    pause: float = PAUSE,
) -> dict:
    """Fino a `attempts` tentativi: basta che uno vada bene."""
    result: dict = {}
    for attempt in range(attempts):
        if attempt:
            time.sleep(pause)
        try:
            result = classify(*fetch(url, TIMEOUT))
        except OSError as exc:      # nessuna risposta: DNS, timeout, connessione chiusa
            reason = getattr(exc, "reason", None) or exc
            result = {"state": "down", "commit": None, "detail": f"nessuna risposta ({reason})"}
        if result["state"] == "ok":
            break
    return result


def _duration(since: str, now: datetime) -> str:
    try:
        minutes = max(0, int((now - datetime.fromisoformat(since)).total_seconds() // 60))
    except (TypeError, ValueError):
        return "un po'"
    if minutes < 60:
        return {0: "meno di un minuto", 1: "1 minuto"}.get(minutes, f"{minutes} minuti")
    hours, minutes = divmod(minutes, 60)
    text = "un'ora" if hours == 1 else f"{hours} ore"
    if minutes:
        text += f" e {minutes} minut{'o' if minutes == 1 else 'i'}"
    return text


def _bad_news(current: dict) -> str:
    if current["state"] == "down":
        return f"🔴 {NAME} non risponde: {current['detail']}"
    return f"🟠 {NAME} risponde, ma {current['detail']}"


def step(
    previous: dict | None, current: dict, now: datetime, subject_of: Callable[[str], str | None],
) -> tuple[str | None, dict, bool]:
    """Com'era e com'è adesso → (cosa dire, cosa ricordare, se è cambiato).

    Il commit si ricorda solo quando il sito sta bene: giù non si sa cosa gira, e
    un deploy uscito zoppo si annuncia quando torna a posto."""
    state = current["state"]
    if state == "ok" or previous is None:
        commit = current["commit"]
    else:
        commit = previous.get("commit")
    if previous is None:
        message = None if state == "ok" else _bad_news(current)
        return message, {"state": state, "commit": commit, "since": now.isoformat()}, True

    lines = []
    if state != previous["state"]:
        if state != "ok":
            lines.append(_bad_news(current))
        else:
            again = "di nuovo su" if previous["state"] == "down" else "di nuovo a posto"
            lines.append(f"🟢 {NAME} è {again}, dopo {_duration(previous.get('since'), now)}")
    if state == "ok" and commit and commit != previous.get("commit"):
        subject = subject_of(commit)
        lines.append(f"🚀 In produzione {commit}" + (f": {subject}" if subject else ""))

    since = previous["since"] if state == previous["state"] else now.isoformat()
    new = {"state": state, "commit": commit, "since": since}
    changed = new != previous
    return ("\n".join(lines) or None), (new if changed else previous), changed


def commit_subject(sha: str) -> str | None:
    """Il titolo del commit, se il checkout lo conosce. Lo sha arriva dalla rete:
    prima di passarlo a git si controlla che sia davvero uno sha."""
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha or ""):
        return None
    try:
        out = subprocess.run(  # noqa: S603, S607 — git dal PATH del runner, argomenti fissi
            ["git", "log", "-1", "--format=%s", sha],
            capture_output=True, text=True, timeout=10, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def send_telegram(token: str, chat_id: str, text: str) -> None:
    data = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20):  # noqa: S310 — URL fisso, https
            return
    except urllib.error.HTTPError as exc:
        # La descrizione di Telegram ("chat not found"…), mai l'indirizzo: contiene il token.
        try:
            description = json.loads(exc.read()).get("description", "")
        except ValueError:
            description = ""
        raise RuntimeError(f"Telegram ha rifiutato il messaggio: HTTP {exc.code} {description}") from None


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _output(name: str, value: str) -> None:
    if target := os.environ.get("GITHUB_OUTPUT"):
        with open(target, "a", encoding="utf-8") as out:
            out.write(f"{name}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lo stato del sito su Telegram, quando cambia.")
    parser.add_argument("--stato", required=True, help="il file dove si ricorda com'era")
    parser.add_argument("--url", default=URL)
    parser.add_argument("--sempre", action="store_true",
                        help="scrive lo stato anche se non è cambiato: per provare bot e segreti")
    args = parser.parse_args(argv)

    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        print("::warning::Mancano TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID: nessun controllo.")
        return 0

    path = Path(args.stato)
    current = check(args.url)
    print(json.dumps(current, ensure_ascii=False))
    message, state, changed = step(_load(path), current, now=datetime.now(UTC), subject_of=commit_subject)
    if args.sempre and not message:
        healthy = f"✅ {NAME} sta bene, commit {current['commit']}."
        message = healthy if current["state"] == "ok" else _bad_news(current)
    if message:
        send_telegram(token, chat_id, message)
        print(message)
    if changed:
        path.write_text(json.dumps(state, ensure_ascii=False))
    _output("cambiato", "true" if changed else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
