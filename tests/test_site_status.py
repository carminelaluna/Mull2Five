"""
test_site_status.py — Lo stato del sito su Telegram, visto da fuori.

`scripts/stato_sito.py` lo lancia GitHub Actions ogni cinque minuti: chiama
/health di mull2five.it e scrive su Telegram solo quando qualcosa cambia — giù,
qualcosa che non va, di nuovo su, un deploy nuovo. Fra un giro e l'altro si
ricorda com'era lasciato in un file. Qui si prova la logica, senza rete.
"""
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "stato_sito.py"
_spec = importlib.util.spec_from_file_location("stato_sito", _PATH)
stato_sito = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stato_sito)

ORA = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _fuori_da_github(monkeypatch):
    """Sul runner di GitHub ci sono GITHUB_REPOSITORY e GITHUB_TOKEN: qui no,
    così main() non chiama l'API dei backup se un test non lo chiede."""
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


def _health(status="ok", database="ok", commit="c8703eb", applicata="0014", attesa="0014"):
    return json.dumps({
        "status": status, "database": database, "cache": "memory", "commit": commit,
        "schema": {"applicata": applicata, "attesa": attesa, "indietro": applicata != attesa},
    })


def _risponde(*risposte):
    """Un fetch finto: ogni chiamata dà la risposta successiva (o solleva)."""
    coda = list(risposte)

    def fetch(url, timeout):
        risposta = coda.pop(0)
        if isinstance(risposta, Exception):
            raise risposta
        return risposta
    return fetch


def _controlla(*risposte):
    return stato_sito.check("https://mull2five.it/health", fetch=_risponde(*risposte), pause=0)


def test_a_healthy_site_is_ok():
    assert _controlla((200, _health())) == {"state": "ok", "commit": "c8703eb", "detail": ""}


def test_no_answer_is_down_only_after_every_attempt():
    giu = _controlla(OSError("timed out"), (502, "Bad Gateway"), OSError("timed out"))
    assert giu == {"state": "down", "commit": None, "detail": "nessuna risposta (timed out)"}

    assert _controlla(OSError("timed out"), (200, _health()))["state"] == "ok"


def test_an_error_page_is_down():
    assert _controlla(*[(502, "Bad Gateway")] * 3) == {"state": "down", "commit": None, "detail": "HTTP 502"}


@pytest.mark.parametrize(("body", "detail"), [
    (_health(status="degraded", database="error"), "il database non risponde"),
    (_health(status="degraded", applicata="0013", attesa="0014"), "lo schema è a 0013 invece che a 0014"),
])
def test_a_site_that_answers_but_limps_is_degraded(body, detail):
    risultato = _controlla(*[(200, body)] * 3)
    assert risultato["state"] == "degraded" and risultato["detail"] == detail


def _passo(prima, ora_health, quando=ORA, oggetto=None):
    return stato_sito.step(prima, ora_health, now=quando, subject_of=lambda sha: oggetto)


OK = {"state": "ok", "commit": "c8703eb", "detail": ""}
GIU = {"state": "down", "commit": None, "detail": "HTTP 502"}


def test_the_first_look_at_a_healthy_site_says_nothing():
    messaggio, stato, cambiato = _passo(None, OK)
    assert messaggio is None and cambiato
    assert stato == {"state": "ok", "commit": "c8703eb", "since": ORA.isoformat()}


def test_the_first_look_at_a_broken_site_says_so():
    messaggio, _, _ = _passo(None, GIU)
    assert messaggio == "🔴 mull2five.it non risponde: HTTP 502"


def test_nothing_new_says_nothing_and_keeps_the_file():
    prima = {"state": "ok", "commit": "c8703eb", "since": "2026-11-20T08:00:00+00:00"}
    assert _passo(prima, OK) == (None, prima, False)


def test_going_down_is_told():
    prima = {"state": "ok", "commit": "c8703eb", "since": "2026-11-20T08:00:00+00:00"}
    messaggio, stato, cambiato = _passo(prima, GIU)
    assert messaggio == "🔴 mull2five.it non risponde: HTTP 502"
    assert cambiato and stato["state"] == "down" and stato["since"] == ORA.isoformat()
    assert stato["commit"] == "c8703eb"      # giù non si sa che commit c'è: resta quello di prima


def test_still_down_says_nothing_again():
    prima = {"state": "down", "commit": "c8703eb", "since": ORA.isoformat()}
    assert _passo(prima, GIU, ORA + timedelta(minutes=5))[0] is None


def test_limping_is_told():
    prima = {"state": "ok", "commit": "c8703eb", "since": ORA.isoformat()}
    zoppo = {"state": "degraded", "commit": "c8703eb", "detail": "il database non risponde"}
    assert _passo(prima, zoppo)[0] == "🟠 mull2five.it risponde, ma il database non risponde"


def test_coming_back_says_after_how_long():
    prima = {"state": "down", "commit": "c8703eb", "since": ORA.isoformat()}
    messaggio, stato, _ = _passo(prima, OK, ORA + timedelta(minutes=23))
    assert messaggio == "🟢 mull2five.it è di nuovo su, dopo 23 minuti"
    assert stato["state"] == "ok"


def test_a_new_commit_is_a_deploy():
    prima = {"state": "ok", "commit": "e333eb5", "since": "2026-11-20T08:00:00+00:00"}
    messaggio, stato, cambiato = _passo(prima, OK, oggetto="Termini e codice d'accordo")
    assert messaggio == "🚀 In produzione c8703eb: Termini e codice d'accordo"
    assert cambiato and stato["commit"] == "c8703eb"
    assert stato["since"] == prima["since"]      # sempre su: non ricomincia il conto


def test_back_up_with_a_new_commit_says_both():
    prima = {"state": "down", "commit": "e333eb5", "since": ORA.isoformat()}
    messaggio, _, _ = _passo(prima, OK, ORA + timedelta(minutes=3))
    assert messaggio == "🟢 mull2five.it è di nuovo su, dopo 3 minuti\n🚀 In produzione c8703eb"


def test_main_sends_then_saves(tmp_path, monkeypatch):
    """Prima si manda, poi si salva: se Telegram non risponde, il giro dopo ci riprova."""
    file = tmp_path / "stato.json"
    file.write_text(json.dumps({"state": "ok", "commit": "c8703eb", "since": ORA.isoformat()}))
    output = tmp_path / "github_output"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(stato_sito, "check", lambda url: GIU)
    inviati = []

    def send(token, chat_id, text):
        inviati.append((token, chat_id, text))

    monkeypatch.setattr(stato_sito, "send_telegram", send)
    assert stato_sito.main(["--stato", str(file)]) == 0
    assert inviati == [("123:abc", "42", "🔴 mull2five.it non risponde: HTTP 502")]
    assert json.loads(file.read_text())["state"] == "down"
    assert output.read_text() == "cambiato=true\n"

    file.write_text(json.dumps({"state": "ok", "commit": "c8703eb", "since": ORA.isoformat()}))

    def rotto(token, chat_id, text):
        raise OSError("Telegram giù")

    monkeypatch.setattr(stato_sito, "send_telegram", rotto)
    with pytest.raises(OSError):
        stato_sito.main(["--stato", str(file)])
    assert json.loads(file.read_text())["state"] == "ok"


def test_run_by_hand_it_always_says_how_it_is(tmp_path, monkeypatch):
    """Lanciato a mano da GitHub ("Run workflow") scrive anche se non è cambiato
    niente: è la prova che bot e segreti funzionano."""
    file = tmp_path / "stato.json"
    file.write_text(json.dumps({"state": "ok", "commit": "c8703eb", "since": ORA.isoformat()}))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(stato_sito, "check", lambda url: OK)
    inviati = []
    monkeypatch.setattr(stato_sito, "send_telegram", lambda token, chat_id, text: inviati.append(text))

    stato_sito.main(["--stato", str(file)])
    stato_sito.main(["--stato", str(file), "--sempre"])

    assert inviati == ["✅ mull2five.it sta bene, commit c8703eb."]


def test_a_token_pasted_with_a_newline_still_works(tmp_path, monkeypatch):
    """Il 24/11/2026 il primo giro vero è caduto così: il segreto copiato da
    BotFather finiva con un a capo, e l'indirizzo di Telegram non era valido."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc\n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", " 42\n")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(stato_sito, "check", lambda url: OK)
    inviati = []
    monkeypatch.setattr(stato_sito, "send_telegram", lambda *args: inviati.append(args[:2]))

    stato_sito.main(["--stato", str(tmp_path / "stato.json"), "--sempre"])

    assert inviati == [("123:abc", "42")]


def test_a_broken_token_never_ends_up_in_the_error():
    """L'errore finisce nel log del workflow: dentro non ci va l'indirizzo, che
    contiene il token. Un a capo nel mezzo lo rifiuta Python prima della rete."""
    with pytest.raises(RuntimeError) as errore:
        stato_sito.send_telegram("segretissimo\nx", "42", "prova")
    assert "segretissimo" not in str(errore.value)


MAIN = "f00ba12" + "0" * 33       # lo sha intero di main, come lo dà GitHub


def _deploy(prima, adesso, main=MAIN, quando=ORA):
    return stato_sito.deploy_step(prima, adesso, main, quando, subject_of=lambda sha: "Backup su Telegram")


def test_main_already_live_leaves_nothing_pending():
    assert _deploy(None, {**OK, "commit": "f00ba12"}) == (None, None)


def test_a_late_deploy_is_told_once_after_twenty_minutes():
    """Il 29/09/2026 un deploy è rimasto appeso per sempre mentre il sito vecchio
    rispondeva: il 🚀 non arrivava, e nessuno se ne accorgeva."""
    messaggio, sospeso = _deploy(None, OK)
    assert messaggio is None and sospeso == {"commit": MAIN, "since": ORA.isoformat(), "told": False}

    messaggio, sospeso = _deploy(sospeso, OK, quando=ORA + timedelta(minutes=10))
    assert messaggio is None

    messaggio, sospeso = _deploy(sospeso, OK, quando=ORA + timedelta(minutes=21))
    assert messaggio == ("⏳ main è a f00ba12 (Backup su Telegram), ma in produzione gira ancora"
                         " c8703eb dopo 21 minuti: il deploy è fallito o è fermo. Render → Mull2Five → Events.")
    assert sospeso["told"]

    assert _deploy(sospeso, OK, quando=ORA + timedelta(minutes=40))[0] is None
    # Quando arriva, non c'è più niente in sospeso (e il 🚀 lo dice step).
    assert _deploy(sospeso, {**OK, "commit": "f00ba12"}, quando=ORA + timedelta(minutes=45)) == (None, None)


def test_a_newer_push_starts_the_clock_again():
    _, sospeso = _deploy(None, OK)
    altro = "abcdef1" + "0" * 33
    messaggio, sospeso = _deploy(sospeso, OK, main=altro, quando=ORA + timedelta(minutes=25))
    assert messaggio is None and sospeso["since"] == (ORA + timedelta(minutes=25)).isoformat()


def test_without_main_or_with_the_site_down_nothing_changes():
    prima = {"commit": MAIN, "since": ORA.isoformat(), "told": False}
    assert _deploy(prima, GIU, quando=ORA + timedelta(hours=1)) == (None, prima)
    assert _deploy(prima, OK, main="", quando=ORA + timedelta(hours=1)) == (None, prima)


def _backup(prima, ultimo, quando=ORA):
    return stato_sito.backup_step(prima, ultimo, quando)


def test_a_recent_backup_says_nothing():
    assert _backup(None, ORA - timedelta(hours=27)) == (None, {"late": False})


def test_a_skipped_backup_is_told_once_and_when_it_is_back():
    """Il 24/11/2026 alle 13 il backup di quella notte non era ancora partito:
    un backup che GitHub non avvia non fallisce, e nessuno lo diceva."""
    messaggio, stato = _backup({"late": False}, ORA - timedelta(hours=31))
    assert messaggio == ("🗄️ Nessun backup riuscito da 31 ore: l'ultimo è del 23/11 alle 06:00."
                         " GitHub → Actions → Backup → Run workflow.")
    assert stato == {"late": True}

    assert _backup(stato, ORA - timedelta(hours=33))[0] is None

    messaggio, stato = _backup(stato, ORA - timedelta(minutes=5))
    assert messaggio == "✅ Backup di nuovo a posto: l'ultimo è del 24/11 alle 12:55."
    assert stato == {"late": False}


def test_no_backup_at_all_is_told():
    assert _backup(None, None)[0] == "🗄️ Non c'è nessun backup riuscito. GitHub → Actions → Backup → Run workflow."


def _con_telegram(monkeypatch, inviati):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(stato_sito, "send_telegram", lambda token, chat_id, text: inviati.append(text))


def test_main_puts_everything_in_one_message_and_keeps_the_old_file(tmp_path, monkeypatch):
    """Il file di prima (solo il sito) si legge ancora; deploy e backup si
    aggiungono accanto, e un giro manda un messaggio solo."""
    file = tmp_path / "stato.json"
    file.write_text(json.dumps({"state": "ok", "commit": "c8703eb", "since": ORA.isoformat()}))
    inviati = []
    _con_telegram(monkeypatch, inviati)
    monkeypatch.setenv("GITHUB_REPOSITORY", "proprietario/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token-del-workflow")
    chiamate = []

    def ultimo(repository, token, api):
        chiamate.append((repository, token))
        return datetime(2026, 11, 20, 9, 0, tzinfo=UTC)

    monkeypatch.setattr(stato_sito, "last_backup", ultimo)
    monkeypatch.setattr(stato_sito, "check", lambda url: GIU)

    stato_sito.main(["--stato", str(file), f"--main={MAIN}"])

    assert chiamate == [("proprietario/repo", "token-del-workflow")]
    assert len(inviati) == 1
    assert inviati[0].startswith("🔴 mull2five.it non risponde: HTTP 502\n🗄️ Nessun backup riuscito da ")
    salvato = json.loads(file.read_text())
    assert salvato["state"] == "down" and salvato["backup"] == {"late": True}
    assert "deploy" not in salvato      # giù non si sa cosa gira


def test_when_github_does_not_answer_the_backup_stays_as_it_was(tmp_path, monkeypatch, capsys):
    file = tmp_path / "stato.json"
    prima = {"state": "ok", "commit": "c8703eb", "since": ORA.isoformat(), "backup": {"late": True}}
    file.write_text(json.dumps(prima))
    inviati = []
    _con_telegram(monkeypatch, inviati)
    monkeypatch.setenv("GITHUB_REPOSITORY", "proprietario/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token-del-workflow")

    def rotto(*args):
        raise OSError("rete giù")

    monkeypatch.setattr(stato_sito, "last_backup", rotto)
    monkeypatch.setattr(stato_sito, "check", lambda url: OK)

    stato_sito.main(["--stato", str(file)])

    assert inviati == []
    assert json.loads(file.read_text()) == prima
    assert "Non so quando è l'ultimo backup: OSError" in capsys.readouterr().out


def test_run_by_hand_it_also_says_the_last_backup(tmp_path, monkeypatch):
    inviati = []
    _con_telegram(monkeypatch, inviati)
    monkeypatch.setenv("GITHUB_REPOSITORY", "proprietario/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token-del-workflow")
    monkeypatch.setattr(stato_sito, "last_backup", lambda *a: datetime.now(UTC) - timedelta(hours=2))
    monkeypatch.setattr(stato_sito, "check", lambda url: OK)
    file = tmp_path / "stato.json"
    file.write_text(json.dumps({"state": "ok", "commit": "c8703eb", "since": ORA.isoformat(),
                                "backup": {"late": False}}))

    stato_sito.main(["--stato", str(file), "--sempre"])

    assert inviati[0].startswith("✅ mull2five.it sta bene, commit c8703eb. Ultimo backup: ")


def test_without_telegram_it_does_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(stato_sito, "check", lambda url: pytest.fail("non deve chiamare il sito"))
    assert stato_sito.main(["--stato", str(tmp_path / "stato.json")]) == 0
