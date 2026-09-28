# Chi può fare cosa

Due cose diverse, che conviene non confondere: il **ruolo dell'account** e
l'**incarico su un torneo**.

## Il ruolo dell'account

- **Giocatore** — si iscrive, carica liste, apre segnalazioni. Non vede il
  back-office e non vede nemmeno la voce "Organizza".
- **Organizzatore** — tutto quello che fa un giocatore, più il back-office: i
  propri tornei e quelli dei negozi di cui fa parte.
- **Admin** — in più: le statistiche del sito, l'import dal Wizards Locator, la
  creazione dei profili dei minori, le segnalazioni indirizzate al sito.

## L'incarico su un torneo

Indipendente dal ruolo: un giocatore può essere capojudge di un torneo.

- **Organizzatore del torneo** — chi l'ha creato, o chi fa parte dello staff
  del negozio che lo organizza. Può tutto, compreso eliminare il torneo e
  vedere i pagamenti.
- **Capojudge** — uno solo per torneo. Fa scorrere i turni, rigenera gli
  abbinamenti, nomina e rimuove i judge. Non elimina il torneo e non vede i
  pagamenti.
- **Judge** — arbitra: risultati, penalità, deck check, tempo supplementare.
  Non decide la struttura del torneo.

## Il negozio

- **Titolare** — apre il negozio, gestisce lo staff, le chiavi API e gli
  incassi.
- **Organizzatore del negozio** — gestisce **tutti** i tornei del negozio, non
  solo quelli che ha creato lui.

## In pratica

| Azione | Chi |
|---|---|
| Creare e modificare un torneo | organizzatore del torneo |
| Avviare il torneo | organizzatore del torneo |
| Generare il turno successivo | organizzatore **o capojudge** |
| Inserire un risultato | organizzatore, capojudge, judge |
| Dare una penalità | organizzatore, capojudge, judge |
| Nominare un judge | organizzatore **o capojudge** |
| Nominare il capojudge | solo l'organizzatore |
| Chiudere il torneo | solo l'organizzatore |
| Vedere i pagamenti | solo l'organizzatore |
