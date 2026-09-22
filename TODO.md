# Mull2Five TODO

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

## Gerarchia giudicante (V2)

- [x] Incarico per-torneo su `TournamentStaff.role`: capojudge o judge, indipendente dal ruolo dell'account.
- [x] L'organizzatore nomina il capojudge (uno solo per torneo), promuove e degrada.
- [x] Il capojudge nomina e rimuove i judge sotto di lui; non puo nominarsi un pari grado ne rimuovere se stesso.
- [x] Lo staff trova il torneo in `/tournaments/mine`, vede i pairing non pubblicati, rilegge penalita e annunci.
- [x] `GET /tournaments/{id}/my-role` per far decidere alla UI quali controlli mostrare.
- [ ] UI: sezione nomina capojudge in organizer.html e nomina judge per il capojudge.
- [x] UI: control.html adatta i controlli al ruolo (`canRunRounds`, chiusura al solo organizzatore).
- [x] Top decklist pubbliche e statistiche archetipi (`/public-meta` e vista grafica nello storico).

## Correzioni segnalate dal campo

- [x] Timer: i datetime tornavano naive da SQLite e il browser li leggeva come ora locale (round da 50' che partiva da -70). `UtcDateTime` li marca UTC all'uscita dal DB.
- [x] Giocatore: puo rileggere e correggere la propria lista fino alla scadenza (`GET /tournaments/{id}/decklist`, `raw_text` in `DecklistOut`).
- [x] Scadenza liste visibile al giocatore e impostabile dal back-office (`decklist_locks_at`, `decklist_locked`).
- [x] Tasto "Chiudi torneo" nella console regia, visibile al solo organizzatore.
- [x] Torneo chiuso: niente nuovi round ne timer, lato API e lato UI.
- [x] Vista grafica delle liste con immagini Scryfall, ripresa dal tool rimosso in V2 (`js/deck-view.js`): giocatore, storico e back-office.
- [x] Tornei conclusi di nuovo visibili al giocatore: il frontend filtrava su `closed`, lo stato reale e `completed`.
- [x] Toggle "liste pubbliche" e scadenza liste esposti nel back-office (l'endpoint `/controls` non era mai chiamato).

## Scoperta eventi e community

- [x] Tassonomia tipi evento (serate, prerelease, RCQ, store championship, premier) con filtro dedicato.
- [x] Ricerca eventi a facet: formati multipli, REL, finestra temporale, distanza in km, ricerche salvate.
- [x] Home "Scopri" a rail per eventi, negozi e circuiti, con chip di filtro rapido.
- [x] Profili pubblici dei negozi (`store.html`) con anagrafica, coordinate, calendario e albo d'oro.
- [x] Circuiti pubblici (`series.html`): periodo, struttura punti, soglia di qualificazione, classifica.
- [x] Tag giocatore per negozio, con assegnazione in blocco dagli iscritti.
- [x] Back-office: tab Negozio (profilo + geocoding Nominatim) e tab Tag.
- [x] Conventions: realizzate come contenitore `Event` (in interfaccia "Manifestazioni").
- [ ] API pubblica con API key e database decklist consultabile.
- [x] Annunci mirati per tag: scelta dei tag nel modulo con il conteggio dei destinatari
      prima dell'invio, filtro su email, push e lettura in pagina. La platea si fissa
      all'invio (`announcement_recipients`): togliere o cancellare un tag dopo non
      allarga ne restringe chi legge.

## Navigazione e permessi

- [x] Generazione e rigenerazione round aperte al capojudge; chiusura torneo resta all'organizzatore.
- [x] Navigazione pubblica da 6 voci a 4: Eventi, Negozi, Circuiti, Organizza.
- [x] Storico assorbito nella ricerca eventi come filtro di stato (niente pagina a parte).
- [x] "Classifica stagionale" sostituita da Circuiti: schede invece di un menu a tendina.
- [x] Back-office da 9 tab a due livelli: Eventi/Community/Negozio, e dentro un evento 5 sezioni.
- [x] Via il selettore globale "torneo attivo": si entra in un evento e si esce.
- [x] Classifica e report uniti in "Risultati"; form di creazione spostato in una modale.
- [x] Iscritti, Liste e Penalità unite nella sezione Giocatori: una riga per persona, schede dell'evento da 6 a 4.
- [x] Console Regia estratta in `js/console.js` e montata dentro la pagina dell'evento; `control.html` resta come versione a tutto schermo per secondo monitor e judge.
- [x] Storico tornei del giocatore: righe cliccabili che aprono statistiche e match round per round del singolo torneo.

## Coverage (spunti dal blog judge FAB)

- [x] Metagame pubblico sui tornei conclusi (`/public-meta`), con barre nello storico.
- [x] Pagina `coverage.html`: scheda con vincitore, top 8 e metagame, export PNG in tre formati social.
- [x] Corretto l'ordine dei campi del record in `meta_stats`: sconfitte lette come pareggi, win rate gonfiato.
- [x] Eventi a formato misto: `Round.format`, una decklist per segmento, UI su giocatore e back-office.
- [ ] Pod di draft con round interni al pod e ri-podding: valutato, rimandato.

## Gestione sala (spunti da Purple Fox)

- [x] Judge assegnato al tavolo: "Prendo io" / libera, col tavolo evidenziato se e il tuo.
- [x] Stato del tavolo (in gioco / chiamato / serve judge); quello deducibile — risultato, conflitto — resta dedotto.
- [x] Deck check registrati per torneo: esito, nota, judge e round; sopravvivono alla rigenerazione del round.
- [x] Contenitore Event: tappe, pagina pubblica, staff con ruoli ereditati su tutti i tornei dentro.
- [x] Flag Day 2 per iscrizione con tasso di conversione per archetipo.
- [x] `Round.format`: segmenti a formato diverso dentro lo stesso torneo (nullo = formato del torneo).
- [x] Piu decklist per iscrizione, una per segmento di formato. Unicita spostata su
      `(registration_id, format)`; su SQLite la tabella viene ricostruita e le righe ricopiate,
      su PostgreSQL bastano due ALTER. `format` vuoto = lista principale.
- [x] UI per le liste di segmento: una riga per segmento sulla scheda iscrizione, selettore
      nel caricamento da banco, colonna che dice quali segmenti mancano.
- [x] UI dell'Event in back-office (sezione "Manifestazioni"): creazione, tappe, staff, anagrafica.
- [x] UI staff del singolo torneo (scheda Staff dentro l'evento): nomina per email,
      promozione e degrado del capojudge, rimozione. I permessi del backend sono
      rispecchiati in interfaccia: il capojudge nomina judge ma non promuove.
- [x] Pagina pubblica della manifestazione (`event-page.html?e=slug`): programma raggruppato per giornata.
- [x] Avvisi all'organizzatore (`services/warnings.py`): tappa fuori periodo, torneo mai
      partito, Stripe/PayPal attivi senza credenziali sul server, scadenza liste dopo
      l'inizio, liste mancanti nelle 48 ore prima, nessun capojudge a REL Competitive o
      superiore, email accese senza SMTP; sulla manifestazione anche pagina pubblica
      senza tappe. Contatore sulle schede (solo gli avvisi, non le note), striscia dentro
      il torneo, badge "fuori periodo" sulle tappe. Un periodo con la fine prima
      dell'inizio ora si rifiuta, e la data di fine si puo svuotare.
- [x] La casella "Invia anche via email" degli annunci non mandava mai niente: il torneo
      doveva avere le notifiche accese e nessuna schermata le accendeva. Ora il modulo
      dice se l'email partira e permette di accenderle.
- [x] Deck check dalla console: pulsante per giocatore nella vista Judge, con esito, nota, storico e segno di gia controllato.

## Verso l'MVP — piano operativo

Tutte le voci dell'MVP sono chiuse.

### Fuori MVP, valutati e rimandati

- Pod di draft con round interni al pod e ri-podding (serve solo al limited oltre i 16 giocatori).
- API pubblica con API key e database decklist consultabile.

### Non fattibile da qui

- Test refund PayPal: servono credenziali sandbox reali e un webhook pubblico.
  Va fatto da te, in un ambiente con `PAYPAL_CLIENT_ID`/`SECRET` configurati.

## Da monitorare

- [ ] Testare refund PayPal con account sandbox reale e webhook `PAYMENT.CAPTURE.COMPLETED`.
- [x] Aggiunta suite `unittest` persistente invece degli smoke test inline.

## Idee per dopo

Dalle vecchie note di sviluppo (`suggestions.md`, tolto: il resto era già fatto).

- Email: promemoria il giorno prima del torneo; link di pagamento diretto quando si viene promossi dalla lista d'attesa.
- Calendario mensile nella parte pubblica ("cosa c'è giovedì?"): i dati ci sono già, manca la griglia.
- Modelli di torneo salvati (oggi c'è "Duplica", con la data spostata di 7 giorni).
- Early bird e codici sconto sulla quota d'iscrizione.
- Profilo giocatore: win rate per formato e per archetipo (record e piazzamenti ci sono già).

## Parità con Melee — piano (settembre 2026)

Decisioni: tutti i punti del confronto tranne l'app mobile; giochi Magic, Lorcana,
Star Wars Unlimited, One Piece, Pokémon; interfaccia in IT, EN, ES, FR, DE; commit su
`main` senza push, si pubblica tutto alla fine con l'ok.

Ordine (le dipendenze decidono): prima i giochi, perché formati, spareggi e ricerca
carte dipendono dal gioco; per ultime le lingue, perché toccano ogni stringa; i
pagamenti ai negozi in fondo, sono il pezzo più grosso.

- [x] 0. Traduzioni: funzione `t()` con il testo italiano come chiave, usata da subito nel codice nuovo
- [x] 1. Più giochi: formati, spareggi ufficiali per gioco, badge e filtro in ricerca. Per ora acceso solo Magic: gli altri si accendono con ENABLED_GAMES (es. "mtg,lorcana" o "all")
- [x] 2. Formato dei match: al meglio di 1/2/3, patte intenzionali sì/no
- [x] Nome dell'organizzatore nella pagina pubblica del torneo, all'iscrizione e nelle iscrizioni del giocatore
- [x] 3. Scheda Impostazioni del torneo (oggi dopo la creazione non si modifica quasi niente)
- [x] 4. Più sedi per negozio: ogni torneo sceglie la sede e ne prende indirizzo e coordinate
- [x] 5. Staff del negozio: titolare e organizzatori gestiscono tutti i tornei del negozio; ogni organizzatore può aprire il suo negozio
- [x] 6. Sospensioni dei giocatori: per negozio, con motivo e scadenza; bloccano le iscrizioni e segnalano chi era già iscritto
- [x] 7. Tornei ricorrenti: ripeti ogni settimana, ogni due o ogni mese; le modifiche possono andare a tutta la serie
- [x] 8. Campi di iscrizione personalizzati: testo, scelta, casella; risposte nella scheda Giocatori e nel CSV degli iscritti
- [x] 9. Eventi di sola iscrizione: iscritti, pagamenti e presenze senza turni né classifica
- [x] 10. Import degli iscritti da file: CSV con virgole o punti e virgola, anteprima riga per riga, poi l'import
- [x] 11. Togli chi non ha pagato (con anteprima, prima dell'avvio); premi consegnati segnati in classifica e nel registro
- [x] 12. Bye assegnati (0-3, prima dell'avvio), bye naturale mai due volte allo stesso giocatore, sconfitta a tavolino per chi non si presenta
- [x] 13. Ospiti al banco senza email; minori come profili gestiti dal genitore (X-Act-As); età minima alla registrazione (MIN_ACCOUNT_AGE, 14)
- [x] 14. Tavoli fissi; pod di draft bilanciati con posti, primo turno di fronte e svizzera nel pod, stampa
- [x] 15. Tornei a squadre: squadre da 2 o 3 con posti A/B/C, abbinamenti posto contro posto, classifica a squadre
- [x] 16. Storico penalità del giocatore per i judge: "N precedenti" nella lista iscritti e storico negli altri tornei nella finestra penalità (le note restano del torneo)
- [x] 17. Regole di mazzo per gioco (Magic: 4 copie fra main e side, base e "qualsiasi numero" liberi, limited 40, Commander singleton 100), bandite e ristrette via Scryfall, ricerca carte, costruttore di liste e liste salvate ("Le mie liste"); gli altri giochi hanno il posto pronto in services/decklists.py
- [x] 18. Archivio pubblico delle liste ("Liste"): le liste dei tornei conclusi con classifica e liste pubbliche, filtri per formato, archetipo, carta, periodo e posizione, metagame (archetipi e carte più giocate) e "Salva tra le mie liste"
- [x] 19. Tornei online (MTG Arena, Magic Online, SpellTable): piattaforma e link della stanza visibile solo agli iscritti, nome in gioco chiesto all'iscrizione (Arena ID controllato) e ricordato, nome dell'avversario negli abbinamenti, filtro "Dove si gioca" nella ricerca
- [x] 20. ID dell'editore e programmi ufficiali: ID evento (EventLink) e inviti (1 negli RCQ), report ufficiale con ID dei giocatori e inviti (anche CSV), ID completabile da staff e giocatore, avviso per gli ID mancanti, ID riproposto all'iscrizione e inviti sul profilo pubblico
- [x] 21. API pubblica con chiavi: chiavi del negozio create e revocate dal titolare (solo l'hash nel database, la chiave si vede una volta), /api/v1 in sola lettura per tornei, iscritti (senza dati personali), abbinamenti e classifiche, limite di richieste per chiave
- [x] 22. Interfaccia in 5 lingue (italiano, inglese, spagnolo, francese, tedesco): selettore nell'header, dizionari con circa 850 voci per lingua, traduzione automatica del markup e dei testi disegnati dalle pagine; restano in italiano i messaggi del server
- [ ] 23. Pagamenti ai negozi (Stripe Connect, PayPal del negozio)
- [ ] App mobile: resta per dopo

Spareggi (dai regolamenti ufficiali):

| Gioco | Match in svizzera | Dopo i punti (V3/P1/S0) |
|---|---|---|
| Magic | al meglio di 3 | OMW% → GW% → OGW%, minimo 33% |
| Lorcana | al meglio di 3 (Challenge: 2) | OMW% → GW% → OGW%, minimo 33% |
| Star Wars Unlimited | al meglio di 3 | OMW% → GW% → OGW%, minimo 33% |
| One Piece | al meglio di 1 (top cut 3) | win rate proprio → medio avversari, minimo 33%, bye esclusi |
| Pokémon | al meglio di 3 | Op Win% (min 25%, max 75% per chi lascia) → Op Op Win% → scontro diretto |

Ricerca carte (passa dal backend: CORS, cache, fonti instabili): Scryfall (Magic),
Lorcast (Lorcana), SWU-DB (Star Wars), optcgapi (One Piece, elenco completo in cache),
TCGdex (Pokémon).

