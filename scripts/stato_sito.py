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
  ⏳ main è avanti e il deploy non arriva: fallito o fermo su Render (--main)
  🗄️ nessun backup riuscito da più di 30 ore, e ✅ quando torna: GitHub a volte
     salta gli eventi pianificati, e un backup saltato non fallisce, non c'è e basta

Il sito sa quando questo controllo smette di passare: lo riconosce dallo
User-Agent (services/site_watch.py), e dopo tre ore senza lo dice lui.

Fra un giro e l'altro si ricorda com'era in un file (--stato), che il workflow
tiene nella cache di GitHub. Senza file è il primo giro: se va tutto bene non
dice niente. Prima manda, poi salva: se Telegram non risponde il workflow
fallisce, GitHub manda un'email, e il giro dopo ci riprova. Con --sempre (il
lancio a mano da GitHub) scrive lo stato anche se non è cambiato niente.

Solo libreria standard: sul runner non si installa niente.
"""
import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

URL = "https://mull2five.it/health"
NAME = "mull2five.it"
ATTEMPTS = 3
PAUSE = 20.0       # secondi fra un tentativo e l'altro
TIMEOUT = 30       # Render può metterci un po' a rispondere dopo un deploy
# Il backup parte "alle 02:30 UTC", ma GitHub lo avvia fra le 7 e le 11: fra uno
# e l'altro possono passare 28 ore senza che niente sia andato storto.
BACKUP_LATE = timedelta(hours=30)
# Un deploy su Render (immagine, migrazioni, avvio) sta sotto i dieci minuti.
DEPLOY_LATE = timedelta(minutes=20)
# Il sito riconosce questo controllo da qui: se smette di passare, avvisa lui.
USER_AGENT = "mull2five-stato-sito"

try:
    _ROME = ZoneInfo("Europe/Rome")
except ZoneInfoNotFoundError:      # una macchina senza fusi orari: meglio UTC che niente
    _ROME = UTC


def fetch(url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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


def _when(moment: datetime) -> str:
    """Un momento in ora italiana: "24/11 alle 13:04"."""
    return moment.astimezone(_ROME).strftime("%d/%m alle %H:%M")


def deploy_step(
    previous: dict | None, current: dict, main_sha: str, now: datetime,
    subject_of: Callable[[str], str | None],
) -> tuple[str | None, dict | None]:
    """main è avanti rispetto a quel che gira → (cosa dire, cosa ricordare).

    Render fa il deploy di ogni push su main: se dopo DEPLOY_LATE in produzione
    c'è ancora il commit di prima, il deploy è fallito o è fermo. È successo
    davvero: una migrazione che aspettava un lock teneva il deploy appeso per
    sempre (29/09/2026), e il sito vecchio intanto rispondeva come se niente fosse.
    Si dice una volta per commit."""
    live = current.get("commit")
    if not main_sha or current["state"] == "down" or not live or live == "sconosciuto":
        return None, previous           # non si sa cosa gira: resta com'era
    if main_sha.startswith(live):
        return None, None               # in produzione c'è main: niente in sospeso
    if previous and previous.get("commit") == main_sha:
        since, told = previous["since"], previous.get("told", False)
    else:
        since, told = now.isoformat(), False
    message = None
    if not told and now - datetime.fromisoformat(since) >= DEPLOY_LATE:
        subject = subject_of(main_sha[:7])
        message = (
            f"⏳ main è a {main_sha[:7]}" + (f" ({subject})" if subject else "")
            + f", ma in produzione gira ancora {live} dopo {_duration(since, now)}:"
            " il deploy è fallito o è fermo. Render → Mull2Five → Events."
        )
        told = True
    return message, {"commit": main_sha, "since": since, "told": told}


def last_backup(repository: str, token: str, api: str = "https://api.github.com") -> datetime | None:
    """Quando è finito l'ultimo backup riuscito; None se non ce n'è nessuno.
    Se GitHub non risponde solleva: allora non si sa, e non si dice niente."""
    request = urllib.request.Request(
        f"{api}/repos/{repository}/actions/workflows/backup.yml/runs?status=success&per_page=1",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 — API di GitHub, https
        runs = json.load(response).get("workflow_runs") or []
    if not runs:
        return None
    return datetime.fromisoformat(runs[0]["updated_at"].replace("Z", "+00:00"))


def backup_step(previous: dict | None, last: datetime | None, now: datetime) -> tuple[str | None, dict]:
    """L'ultimo backup riuscito → (cosa dire, cosa ricordare). Un backup che
    fallisce lo dice il workflow Avvisi; questo è per quello che non parte."""
    late = last is None or now - last > BACKUP_LATE
    was_late = bool(previous and previous.get("late"))
    message = None
    if late and not was_late:
        if last is None:
            message = "🗄️ Non c'è nessun backup riuscito."
        else:
            message = (f"🗄️ Nessun backup riuscito da {_duration(last.isoformat(), now)}:"
                       f" l'ultimo è del {_when(last)}.")
        message += " GitHub → Actions → Backup → Run workflow."
    elif was_late and not late:
        message = f"✅ Backup di nuovo a posto: l'ultimo è del {_when(last)}."
    return message, {"late": late}


def send_telegram(token: str, chat_id: str, text: str) -> None:
    data = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data, headers={"Content-Type": "application/json"},
    )
    # Negli errori la descrizione di Telegram ("chat not found"…) o il tipo, mai
    # l'indirizzo: contiene il token, e l'errore finisce nel log del workflow.
    try:
        with urllib.request.urlopen(request, timeout=20):  # noqa: S310 — URL fisso, https
            return
    except urllib.error.HTTPError as exc:
        try:
            description = json.loads(exc.read()).get("description", "")
        except ValueError:
            description = ""
        raise RuntimeError(f"Telegram ha rifiutato il messaggio: HTTP {exc.code} {description}") from None
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise RuntimeError(f"Telegram non raggiungibile: {type(exc).__name__}") from None


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
    parser.add_argument("--main", default="",
                        help="lo sha di main: se non arriva in produzione, lo si dice")
    args = parser.parse_args(argv)

    # Un segreto incollato da BotFather può portarsi dietro un a capo (24/11/2026).
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not (token and chat_id):
        print("::warning::Mancano TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID: nessun controllo.")
        return 0

    path = Path(args.stato)
    saved = _load(path) or {}
    # Il sito sta in cima al file (com'era prima che ci fossero deploy e backup).
    site_before = {key: saved[key] for key in ("state", "commit", "since") if key in saved} or None
    now = datetime.now(UTC)
    current = check(args.url)
    print(json.dumps(current, ensure_ascii=False))

    site_message, state, _ = step(site_before, current, now=now, subject_of=commit_subject)
    state = dict(state)
    deploy_message, deploy = deploy_step(saved.get("deploy"), current, args.main, now, commit_subject)
    if deploy:
        state["deploy"] = deploy
    backup_message, backup = None, saved.get("backup")
    known, last = _last_backup()
    if known:
        backup_message, backup = backup_step(backup, last, now)
    if backup is not None:
        state["backup"] = backup

    message = "\n".join(m for m in (site_message, deploy_message, backup_message) if m) or None
    if args.sempre and not message:
        healthy = f"✅ {NAME} sta bene, commit {current['commit']}."
        message = healthy if current["state"] == "ok" else _bad_news(current)
        if last:
            message += f" Ultimo backup: {_when(last)}."
    if message:
        send_telegram(token, chat_id, message)
        print(message)
    changed = state != saved
    if changed:
        path.write_text(json.dumps(state, ensure_ascii=False))
    _output("cambiato", "true" if changed else "false")
    return 0


def _last_backup() -> tuple[bool, datetime | None]:
    """(se si sa, quando): sul runner di GitHub, con il token del workflow."""
    repository, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not (repository and token):
        return False, None
    try:
        return True, last_backup(repository, token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    except (OSError, ValueError, KeyError, http.client.HTTPException) as exc:
        print(f"::warning::Non so quando è l'ultimo backup: {type(exc).__name__}")
        return False, None


if __name__ == "__main__":
    sys.exit(main())
