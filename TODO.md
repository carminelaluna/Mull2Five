# Arcana Events TODO

Funzioni derivate dall'analisi di Melee.gg e adattate al progetto.

## Implementate

- [x] Backend Python FastAPI con DB relazionale per utenti, tornei, iscrizioni, decklist, pagamenti, round e pairings.
- [x] Login email/password e predisposizione OAuth Google/Apple.
- [x] Ruoli player/organizer e tab "Crea evento" visibile solo agli organizzatori.
- [x] Iscrizione torneo con pagamento Stripe/PayPal in sandbox/mock.
- [x] Dashboard profilo con tornei attuali e passati.
- [x] Dashboard organizer con iscritti, pagamento, check-in, drop e link decklist.
- [x] Start torneo, generazione round svizzera, eliminazione diretta e svizzera + top cut.
- [x] Blocco creazione turno successivo finche tutti i risultati del round corrente sono riportati.
- [x] Lock dei risultati dei round precedenti quando viene creato un round successivo.
- [x] Chiusura e cancellazione torneo.
- [x] Classifica con punti, record e tiebreaker stile MTG.
- [x] Decklist con distinzione Main Deck / Sideboard e immagini Scryfall.
- [x] Supporto carte double-faced/MDFC nelle immagini decklist.
- [x] Export classifica, iscritti e decklist.
- [x] Deadline decklist e blocco invio dopo scadenza o dopo start torneo.
- [x] Audit log delle revisioni decklist.
- [x] Controlli organizer per pubblicare/nascondere pairings e classifica.
- [x] Timer round con durata configurabile e orari inizio/fine round.
- [x] Report risultato da parte dei player seduti al tavolo.
- [x] Late registration configurabile.

## Implementate in questa iterazione

- [x] Player card con storico partite, stato pagamento, check-in, decklist e penalita.
- [x] Modifica manuale pairings da organizer con controllo registrazioni, bye e lock round precedenti.
- [x] Penalita e strumenti judge: warning, game loss, match loss, disqualification e note private.
- [x] Sistema messaggi/annunci evento visibile a organizer e giocatori iscritti.
- [x] Check-in self-service lato player quando abilitato dall'organizer.
- [x] Export avanzato CSV stile EventLink/Companion per gli iscritti.
- [x] Policy rimborsi e richiesta refund lato player.
- [x] Inviti/access code per eventi privati con numero massimo utilizzi.
- [x] Bracket visuale dati per top cut/eliminazione e seed top cut gia configurabile.
- [x] Verifica legale decklist via Scryfall quando abilitata, oltre al conteggio base.
- [x] Notifiche email come flag sugli annunci, pronte per provider SMTP/transazionale.
- [x] Pannello admin API per utenti, tornei e audit pagamenti.

## Rifinite

- [x] Sostituiti prompt/alert temporanei della UI organizer con modali dedicate.
- [x] Collegato invio email SMTP per annunci evento quando configurato.
- [x] Collegato refund Stripe reale quando configurato; PayPal resta protetto da errore esplicito se non configurato.
- [x] Aggiunta vista bracket grafica in modale, raggruppata per round.

## Stabilizzate

- [x] Collegato refund PayPal automatico tramite capture ID reale.
- [x] Trasformato il bracket grafico in bracket interattivo con inserimento risultati.
- [x] Aggiunti template email HTML brandizzati per annunci evento.
- [x] Avanzamento top cut/eliminazione basato sui vincitori del round bracket precedente.
- [x] Controlli anti-conflitto nella modifica manuale pairings.

## Da monitorare

- [ ] Testare refund PayPal con account sandbox reale e webhook `PAYMENT.CAPTURE.COMPLETED`.
- [x] Aggiunta suite `unittest` persistente invece degli smoke test inline.
