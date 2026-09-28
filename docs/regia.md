# La regia

La schermata che si tiene aperta in sala mentre si gioca. Sta dentro l'evento
(scheda **Regia**) e anche a tutto schermo su `control.html`, per un secondo
monitor o per i judge, che nel back-office non entrano.

## Cosa c'è

- **Il timer del turno** — avvia, ferma, +5′, +10′. Quello che vedono i
  giocatori sugli schermi in sala è lo stesso.
- **Gli schermi** — i link alle pagine da proiettare: abbinamenti e classifica
  (`display.html`) e il solo timer (`timer.html`). Non chiedono accesso.
- **I tavoli** — una riga per tavolo, ordinati per numero.
- **La classifica** — sotto i tavoli, richiudibile. È la prima cosa che
  chiedono al banco.
- **Genera turno successivo** e **Chiudi torneo**.

## Su ogni tavolo

- Il **punteggio**, da una tendina con i soli risultati possibili per quel
  formato (al meglio di 1, 3, playoff). Un risultato già inserito si blocca e
  si cambia con "Modifica": la correzione finisce nel registro, con chi l'ha
  fatta.
- Il **cronometro del tavolo** e i pulsanti +2′ / +5′ per il tempo supplementare.
- **Prendo io** — un judge si assegna il tavolo, così due judge non ci vanno
  insieme.
- **⚑** — cambia lo stato del tavolo: in gioco, chiamato, serve judge.
- **✎** — cambia chi gioca a quel tavolo o il numero del tavolo. Compare solo
  sull'ultimo turno e solo finché non c'è un risultato.

## La vista judge

Un interruttore in alto. Aggiunge, su ogni tavolo:

- **⚠ warning** e **GL game loss** per ciascuno dei due giocatori;
- **🔍 deck check**, con il segno di spunta se quella lista è già stata
  controllata — senza, due judge rifanno lo stesso controllo;
- **🚫 non presentato**, che chiude il match a tavolino.

Una **sconfitta a tavolino** (match loss) e una **squalifica** chiudono il
tavolo 2-0 per l'avversario, da sole. Un **game loss** no: quella è una
partita, il match si gioca lo stesso.

## Chi si ritira

Dal turno successivo non viene più abbinato, ma **resta in classifica** con
quello che ha fatto fino a lì — segnato come "ritirato". I suoi spareggi si
calcolano sui turni che ha giocato davvero, senza gonfiarli con quelli saltati.

## Se c'è uno scorekeeper

Con uno scorekeeper nello staff, il risultato che inserisce un judge non va
subito in classifica: il tavolo mostra "Proposto 2 – 1" e resta lì finché chi
tiene il tabellone preme **Conferma**. Chi ha proposto non può confermare da
solo. Se nello staff non c'è nessuno scorekeeper non cambia niente: i judge
scrivono direttamente.

## Chi può fare cosa

Far scorrere i turni e chiudere il torneo sono cose da **organizzatore o
capojudge**. Un judge semplice arbitra i tavoli: inserisce risultati, dà
penalità, registra deck check, allunga il tempo di un tavolo.
