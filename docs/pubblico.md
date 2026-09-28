# Il lato pubblico

Quello che vede chi non ha ancora un account, e quello che un giocatore usa
tutti i giorni.

## Trovare un torneo

- **Home** — eventi, negozi e circuiti della zona, con i filtri rapidi.
- **Eventi** (`events.html`) — la ricerca vera: nome, stato (in programma o
  conclusi), dove si gioca (ovunque, nei negozi, online), tipo di evento,
  formato, REL, periodo, distanza. Lo stato della ricerca sta nell'indirizzo:
  ogni ricerca è un link da mandare a qualcuno.
- **Negozi** e **Circuiti** — gli elenchi, con le pagine pubbliche di ciascuno.
- **Liste** (`decklists.html`) — l'archivio delle liste dei tornei conclusi che
  le hanno rese pubbliche, con il metagame.

"Usa la mia posizione" ordina per distanza. La posizione resta sul dispositivo.

## Iscriversi

Dalla pagina del torneo. Serve un account; se il torneo lo chiede, si risponde
anche alle domande dell'organizzatore. Il pagamento è online (Stripe o PayPal)
o al banco, secondo com'è configurato il torneo.

Un torneo concluso non accetta iscrizioni, nemmeno se la data è più avanti.

## Le mie iscrizioni

`my-registrations.html`, il pannello del giocatore:

- i tornei a cui sei iscritto, con stato del pagamento e check-in;
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
