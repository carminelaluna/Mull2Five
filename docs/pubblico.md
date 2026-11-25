# Il lato pubblico

Quello che vede chi non ha ancora un account, e quello che un giocatore usa
tutti i giorni.

## Trovare un torneo

- **Home** — eventi, negozi e circuiti della zona, con i filtri rapidi.
- **Eventi** (`events.html`) — la ricerca vera: nome, stato (in programma o
  conclusi), dove si gioca (ovunque, nei negozi, online), tipo di evento,
  formato, REL, periodo, distanza. Lo stato della ricerca sta nell'indirizzo:
  ogni ricerca è un link da mandare a qualcuno. In alto a destra si passa da
  **Elenco** a **Mese**: gli stessi filtri su una griglia, lunedì a sinistra,
  con oggi evidenziato e le frecce per cambiare mese — è la risposta a "cosa
  c'è giovedì?". Sul telefono le sette colonne diventano l'elenco dei giorni in
  cui si gioca davvero.
- **Negozi** e **Circuiti** — gli elenchi, con le pagine pubbliche di ciascuno.
- **Liste** (`decklists.html`) — l'archivio delle liste dei tornei conclusi che
  le hanno rese pubbliche, con il metagame.

"Usa la mia posizione" ordina per distanza. La posizione resta sul dispositivo.

## Iscriversi

Dalla pagina del torneo. Serve un account; se il torneo lo chiede, si risponde
anche alle domande dell'organizzatore. Il pagamento è online (Stripe o PayPal)
o al banco, secondo com'è configurato il torneo; dove i pagamenti online sono
spenti (oggi la produzione) si paga solo al banco.

**Non si è iscritti senza pagare o senza scegliere il banco.** Il modulo mostra
solo i modi che il torneo accetta su questo sito:

- **al banco**: iscritto subito, la quota si paga il giorno del torneo;
- **Stripe o PayPal**: "Iscriviti e paga" porta dritto al pagamento. Il posto è
  tenuto per **30 minuti**; l'iscrizione vale quando il pagamento arriva, e solo
  allora parte l'email di conferma. Chi annulla su Stripe o PayPal torna alla
  pagina del torneo, non è iscritto e il posto si libera subito; chi chiude e
  basta lo perde allo scadere (un controllo ogni due minuti), e può iscriversi
  di nuovo. Il posto tenuto conta per la capienza: chi arriva dopo, a torneo
  pieno, va in lista d'attesa e viene promosso se il posto si libera.

Un torneo gratuito non chiede niente; uno solo online, con una quota, rifiuta
l'iscrizione senza un pagamento online. Se Stripe o PayPal rifiutano il
pagamento, l'iscrizione non nasce.

La quota scritta sul pulsante è quella di adesso: se il negozio ha messo una
quota **early bird**, fino a quella data si paga meno, e la pagina lo dice con
la data e il prezzo pieno accanto. Conta il giorno in cui si paga: chi si
iscrive in tempo e paga al banco dopo quella data paga la quota piena. Chi ha
un **codice sconto** lo scrive nel modulo d'iscrizione: un codice scaduto,
esaurito o di un altro torneo blocca l'iscrizione subito, invece di far credere
a uno sconto che al banco non c'è. Da lì in poi quel prezzo è suo, anche se
il negozio ritira il codice.

Un torneo concluso non accetta iscrizioni, nemmeno se la data è più avanti.

**La lista già fatta.** Se il torneo chiede la lista e chi si iscrive ne ha di
salvate in "Le mie liste", il modulo d'iscrizione ha un menu **La tua lista**
(uno per porzione in un evento misto): prima le liste del formato del torneo,
mai quelle di un altro gioco o vuote. La lista scelta parte insieme
all'iscrizione, prima di andare a pagare; se l'invio non riesce l'iscrizione
resta, e la pagina di ringraziamento ricorda di caricarla. Chi iscrive il
figlio sceglie fra le liste del figlio. Da iscritto, accanto a "✓ Iscritto",
**Invia la lista** (o **Cambia la lista**, se è già arrivata) apre lo stesso
menu, finché le liste sono aperte; per incollarla o caricarla da file si passa
da "Le mie iscrizioni". Una lista che non rispetta le regole del formato
arriva lo stesso, e il messaggio dice di controllarla. Chi sceglie la lista e
poi non paga online sparisce dal torneo con la lista; quella salvata resta.

**Il QR dell'iscrizione.** Sotto il pulsante d'iscrizione, finché il torneo è
aperto (non quelli importati dal Locator), c'è **▦ QR iscrizione**: apre una
finestra col QR, da far inquadrare a chi è accanto, con "Copia link" e il
"Foglio da stampare" (`qr.html`, lo stesso del back-office). Lo vede chiunque:
il QR contiene solo l'indirizzo della pagina. Chi lo inquadra arriva su
`event.html?id=<id>&iscriviti=1`, e la finestra d'iscrizione si apre da sola;
senza accesso passa dal login e torna lì.

## Le mie iscrizioni

`my-registrations.html`, il pannello del giocatore:

- i tornei a cui sei iscritto, con la quota che devi davvero — early bird e
  codice sconto già contati, col codice accanto — lo stato del pagamento e il
  check-in;
- il **tuo abbinamento** del turno in corso e, richiudibili, **tutti gli
  abbinamenti** e la **classifica completa**, con la tua riga evidenziata
  (se il torneo non li nasconde);
- il **check-in** da solo, quando l'organizzatore lo permette;
- la **lista**: si carica, si corregge fino alla scadenza, si sceglie fra
  quelle salvate o si carica da file;
- il **ritiro** e l'annullamento dell'iscrizione. Si annulla finché il torneo
  non è iniziato; se avevi pagato e mancano più di 24 ore, il rimborso parte da
  solo quando si può: pagato online sul conto della piattaforma, Stripe o
  PayPal lo restituiscono subito. Pagato al banco, sul PayPal del negozio o con
  un rimborso che il fornitore rifiuta, resta **rimborso richiesto** e lo
  decide l'organizzatore; il messaggio dopo l'annullamento dice quale dei due.
  Se è il negozio ad annullare un torneo in cui c'erano pagamenti, chi era
  ancora iscritto lo trova qui come **Annullato**; chi aveva già annullato no.
  La quota torna indietro a tutti, anche a meno di 24 ore e a chi si era
  ritirato tenendola, perché il torneo non si gioca: pagata online sul conto
  della piattaforma parte subito, le altre restano **rimborso richiesto** e le
  decide il negozio (tutte, se il torneo era già iniziato);
- i **profili che gestisci** (i figli): li iscrivi e paghi tu, al tavolo
  giocano col loro nome. Per aggiungerne uno si apre una segnalazione: nasce un
  account per un minore, quindi lo creiamo noi.

## Entrare: password o Google

`login.html` ha le due schede, **Accedi** e **Registrati**, e sotto, dopo un
"oppure", il bottone **Accedi con Google** (o **Registrati con Google**, a
seconda della scheda). Il bottone c'è solo se il sito ha le credenziali Google
(`GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET`, vedi `docs/hosting.md`).

Con Google succede una di tre cose:

- **l'account Google è già collegato** a un account di qui: si entra in quello;
- **c'è già un account con la stessa email** (aperto con la password, o creato
  al banco dall'organizzatore): si entra in quello e Google gli resta collegato.
  Nessun doppione. **Se l'account aveva una password, questa si spegne**, e con
  lei le sessioni aperte e i link di reset già spediti; arriva un'email che lo
  spiega. Il motivo: la registrazione con la password non verifica l'email, e
  chi avesse aperto un account con l'indirizzo di un altro resterebbe dentro con
  la sua password. Chi la vuole ancora ne sceglie una nuova da "Password
  dimenticata". Succede solo alla prima unione: dopo, Google è già collegato;
- **nessun account**: un ultimo passo chiede nome, età minima, termini e tipo di
  account, come la registrazione con la password, e l'account nasce.

Vale solo un'email che Google ha verificato: le altre vengono rifiutate.

Nel riquadro **Il tuo account** di `my-registrations.html`:

- **Collega Google** — collega l'account Google a quello con cui sei dentro,
  anche se ha un'altra email. Qui la password resta: chi è dentro ha già
  dimostrato di conoscerla;
- **Scollega Google** — solo se resta la password per entrare;
- **Scegli una password** — per chi non ne ha una (nato con Google, o con la
  password spenta dall'unione): arriva
  l'email di "Password dimenticata". Dopo, Google si può scollegare.

Il collegamento con Google finisce nel file di "Scarica i miei dati" e sparisce
con "Elimina account".

## Il profilo pubblico

`player.html?p=…`, raggiungibile da "Profilo" e dal link che si può copiare.
L'indirizzo usa un identificativo casuale, mai l'email: si condivide senza
rivelare niente.

Ci sono punti, record, tornei giocati e inviti ottenuti, lo storico torneo per
torneo e — per chi ha giocato — **dove vince**: il win rate per formato e per
archetipo, l'uno accanto all'altro. Un 50% complessivo può essere 75% in Modern
e 25% in Legacy, e finché c'era solo il totale non si vedeva. Contano solo i
tornei con la classifica pubblica; l'archetipo compare se è stato scritto con
la lista.

## Le email che arrivano

Solo se l'organizzatore tiene accese le email del torneo:

- **iscrizione confermata**, **abbinamenti pronti**, **torneo iniziato**,
  **pagamento ricevuto**;
- il **promemoria del giorno prima**, una volta sola, con dove e quando si
  gioca, il link alla pagina del torneo e — se risulti ancora da pagare — la
  quota che manca;
- la **promozione dalla lista d'attesa**: il posto si è liberato ed è tuo.
  Se il torneo si paga solo online, è tuo per sei ore, con il link per pagare e
  l'ora entro cui farlo: scadute quelle, torni in fondo alla coda e il posto
  passa al prossimo. Al banco o gratis non c'è nessuna scadenza: l'email dice
  solo la quota da pagare il giorno del torneo. Dopo l'inizio del torneo
  l'orologio si ferma.

Sempre, anche con le email del torneo spente: il **torneo annullato**, dalla
casella dei pagamenti, a chi era iscritto o in lista d'attesa e a chi aveva una
quota di mezzo. Dice cosa succede alla quota: il rimborso è partito e torna sul
metodo con cui si è pagato, oppure la richiesta è registrata e la restituisce
il negozio; chi non aveva pagato non deve fare niente.

## La campanella

Dal 25/11/2026, in alto accanto alla lingua, a chi è collegato: lo **storico
delle notifiche**, in un menu a tendina. Ci finisce tutto quello che il sito
dice da solo — iscrizione confermata o lista d'attesa, posto liberato,
pagamento ricevuto, promemoria del giorno prima, torneo iniziato, abbinamenti
di ogni turno, annunci dell'organizzatore, torneo annullato, segnalazioni nuove
e risposte — **anche con le email del torneo spente**: quell'interruttore
spegne le email, non la campanella. Le risposte alle segnalazioni, che email
non ne mandano, arrivano solo qui.

Il numero sulla campanella sono quelle non lette; aprire il menu le segna come
viste, e quelle nuove restano evidenziate finché è aperto. Ogni riga porta alla
pagina giusta (il torneo, Le mie iscrizioni, Segnalazioni). Un genitore vede
anche quelle dei profili che gestisce, con "Per <nome>". Dopo 90 giorni se ne
vanno da sole; con l'account se ne vanno tutte, e l'esportazione dei dati le
contiene.

Come è fatta: `services/inbox.py` le scrive (le chiamano `services/notifications.py`,
gli annunci, la lista d'attesa, il promemoria, le risposte alle segnalazioni),
`routers/notifications.py` le serve (`GET /api/notifications`, `/unread`,
`POST /read`), `js/inbox.js` le mostra. Il server salva il tipo e i pezzi della
frase, non la frase: la scrive chi la mostra, nella lingua di chi legge. Un tipo
nuovo vuole la sua frase in `phrase()` (e nell'app), o compare come "Notifica".

## Le mie liste

`decks.html`. Un costruttore con ricerca carte e controllo delle regole del
formato, oppure la modalità testo. Da qui una lista si può **inviare
direttamente a un torneo** a cui sei iscritto, senza copiare e incollare. Lo
stesso al contrario: dalla pagina del torneo (iscrivendosi o da iscritto) e
dalla finestra "Carica lista" di "Le mie iscrizioni" si sceglie una delle liste
salvate. Quali offrire e in che ordine lo decide `js/saved-decks.js`.

**Come si guarda una lista** (`js/deck-view.js`, dal 25/11/2026), uguale
nell'archivio, nello storico, in Le mie iscrizioni, nel costruttore e nel
back-office. Tre modi:

- **Immagini**: le carte del main ordinate per tipo, poi per costo, poi per
  nome, con il numero di copie sulla carta; il sideboard in colonna a destra,
  le carte una sopra l'altra in modo che se ne leggano i titoli. Sul telefono
  il sideboard va sotto.
- **Testo**: la lista divisa per tipo (Creature, Istantanei, Terre…) con il
  costo di mana.
- **Grafica**: un'immagine da scaricare e condividere, 16:9 o 1:1 — titolo,
  giocatore, torneo, piazzamento, il main e il sideboard. La disegna il browser
  su un canvas.

Le carte le chiede il server a Scryfall (`POST /api/cards/lookup`, con la cache;
pubblica, perché l'archivio è pubblico): il browser non può chiamare
`api.scryfall.com`, che la Content-Security-Policy non permette, ed è per questo
che prima le immagini non comparivano. Le immagini arrivano da
`cards.scryfall.io`, che `img-src` permette e che manda gli header CORS: senza,
la grafica non si potrebbe scaricare.

## Segnalazioni

`tickets.html`. Si apre una segnalazione e si sceglie a chi:

- **all'organizzatore di un torneo** — un risultato sbagliato, un pagamento,
  un profilo da aggiungere;
- **a chi tiene il sito** — un account, qualcosa di rotto.

Chi la riceve risponde nella stessa conversazione. Finché aspetti è "In
attesa"; quando ti rispondono diventa "Risposta". Una segnalazione chiusa si
può riaprire.

**Chi la riceve lo sa per email** (dal 25/11/2026): quando ne nasce una,
"Nuova segnalazione: <oggetto>" arriva a chi può leggerla, tranne chi l'ha
aperta — gli admin se è per il sito; se è per un torneo chi lo organizza, chi
tiene l'evento che lo contiene e lo staff del negozio (`recipients` in
`routers/tickets.py`). Dentro ci sono il primo messaggio e il link a
`tickets.html`, dove si risponde dalla scheda **Ricevute** (compare solo a chi ne
ha). Le risposte successive non mandano email.
