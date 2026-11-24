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
la data e il prezzo pieno accanto. Chi ha un **codice sconto** lo scrive nel
modulo d'iscrizione: un codice scaduto, esaurito o di un altro torneo blocca
l'iscrizione subito, invece di far credere a uno sconto che al banco non c'è.
Da lì in poi quel prezzo è suo, anche se il negozio ritira il codice.

Un torneo concluso non accetta iscrizioni, nemmeno se la data è più avanti.

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
- il **ritiro** e l'annullamento dell'iscrizione;
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
  Nessun doppione, e la password continua a valere. Se l'account aveva una
  password arriva un'email che lo dice: se la password non l'aveva scelta chi
  ha l'email, la cambi da "Password dimenticata";
- **nessun account**: un ultimo passo chiede nome, età minima, termini e tipo di
  account, come la registrazione con la password, e l'account nasce.

Vale solo un'email che Google ha verificato: le altre vengono rifiutate.

Nel riquadro **Il tuo account** di `my-registrations.html`:

- **Collega Google** — collega l'account Google a quello con cui sei dentro,
  anche se ha un'altra email;
- **Scollega Google** — solo se resta la password per entrare;
- **Scegli una password** — per chi è nato con Google e non ne ha una: arriva
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
- la **promozione dalla lista d'attesa**: il posto si è liberato ed è tuo per
  sei ore, con il link per pagare e l'ora entro cui farlo. Scadute quelle, torni
  in coda e il posto passa al prossimo.

## Le mie liste

`decks.html`. Un costruttore con ricerca carte e controllo delle regole del
formato, oppure la modalità testo. Da qui una lista si può **inviare
direttamente a un torneo** a cui sei iscritto, senza copiare e incollare.

## Segnalazioni

`tickets.html`. Si apre una segnalazione e si sceglie a chi:

- **all'organizzatore di un torneo** — un risultato sbagliato, un pagamento,
  un profilo da aggiungere;
- **a chi tiene il sito** — un account, qualcosa di rotto.

Chi la riceve risponde nella stessa conversazione. Finché aspetti è "In
attesa"; quando ti rispondono diventa "Risposta". Una segnalazione chiusa si
può riaprire.
