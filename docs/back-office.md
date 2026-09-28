# Il back-office

`organizer.html` — riservato a chi ha un account da organizzatore o admin. Un
giocatore che ci arriva trova una spiegazione, non una pagina vuota.

Quattro sezioni in cima: **Eventi**, **Manifestazioni**, **Community**,
**Negozio**.

## Eventi

L'elenco dei tuoi tornei, i prossimi sopra e i conclusi in fondo. I conclusi
restano consultabili e non si eliminano: sono lo storico del negozio.

Su ogni scheda: un contatore di avvisi (solo quelli veri, non le note) e le
azioni rapide — Avvia, Regia a parte, Modifica, Duplica, Ripeti, Chiudi.

**Nuovo evento** chiede il minimo: nome, gioco, formato (da una tendina, con
"Altro" per i formati di casa), data e ora, luogo e città, posti, quota. Se il
negozio ha delle sedi, ne scegli una e luogo e città li eredita da lì.

**Ripeti** crea una serie: ogni settimana, ogni due o ogni mese. Le modifiche
fatte dopo possono andare a tutta la serie o solo alla tappa aperta.

**Importa calendario** carica un foglio di calcolo, un torneo per riga.
L'anteprima parte da sola: ti dice riga per riga cosa succederebbe prima di
importare, e ricaricare lo stesso file non crea doppioni.

### Dentro un evento

Cinque schede: **Regia**, **Giocatori**, **Annunci**, **Staff**,
**Impostazioni**, **Risultati**. Un evento di sola iscrizione non ha Regia né
Risultati, perché non ha turni.

- **Giocatori** — una riga per persona: pagamento, check-in, lista, penalità,
  tag. Da qui si iscrive al banco, si importa da file, si tolgono i non
  paganti, si fanno i pod di draft e le squadre.
- **Annunci** — un messaggio a chi è iscritto, in pagina e via email o push se
  accese. Si può restringere ai portatori di certi tag: vedi sotto.
- **Staff** — chi ti aiuta su *questo* torneo: capojudge (uno solo) e judge.
- **Impostazioni** — tutto il resto: struttura, turni previsti, timer, scadenza
  liste, visibilità di abbinamenti e classifica, domande all'iscrizione.
- **Risultati** — classifica, premi consegnati, report ufficiale ed esportazioni.

## Manifestazioni

Un contenitore di tornei che si svolgono insieme (un weekend, una convention).
Ha una pagina pubblica con il programma raggruppato per giornata, e uno staff
che vale su tutte le tappe.

## Community

Due cose che riguardano le **persone**, non i singoli tornei.

### I tag

Un tag è un'etichetta che **il tuo negozio** mette ai propri clienti: "Nuovo",
"Habitué", "Gioca solo Commander". Vive dentro il tuo negozio — la stessa
persona può essere "Habitué" da te e sconosciuta altrove.

Si crea in Community (nome, colore, descrizione) e si assegna in blocco:
scegli un torneo, scegli il tag, spunti i giocatori e assegni.

**A cosa servono davvero**, cioè la parte che mancava:

1. **Filtrare gli iscritti.** Nella scheda Giocatori i tag compaiono accanto ai
   nomi, e puoi cercare per tag: "chi sono i nuovi stasera?" prima di iniziare.
2. **Mandare annunci mirati.** Nel modulo degli annunci puoi scegliere uno o
   più tag: il messaggio va solo a chi ne porta **almeno uno**. È un'unione,
   non un'intersezione — "Nuovi" più "Commander" vuol dire *entrambi i gruppi*,
   non chi sta in tutti e due. Senza tag l'annuncio va a tutti gli iscritti,
   che è il caso normale.

Prima di inviare il modulo ti dice **quanti destinatari** sono.

Un dettaglio che conta: la platea si fissa **al momento dell'invio**. Se dopo
togli un tag a qualcuno, o cancelli il tag, chi ha già ricevuto l'annuncio
continua a vederlo — e chi non l'ha ricevuto non se lo ritrova.

### Le sospensioni

Una sospensione vale per gli eventi **del tuo negozio**, con motivo e scadenza.
Blocca le iscrizioni nuove e segnala chi era già iscritto. Senza data vale
finché non la revochi.

## Negozio

Il profilo pubblico che i giocatori vedono, e tutto quello che sta intorno:

- **Profilo** — nome, città, indirizzo, descrizione, sito, logo, coordinate.
  Senza coordinate il negozio non compare nella ricerca per distanza; il
  pulsante "Trova coordinate dall'indirizzo" le cerca per te.
- **Sedi** — i posti dove si gioca. Un torneo sceglie una sede ed eredita
  indirizzo, città e coordinate.
- **Incassi online** — Stripe e PayPal, con la quota della piattaforma.
- **Staff del negozio** — titolare e organizzatori: gestiscono *tutti* i tornei
  del negozio, non solo i propri.
- **Chiavi API** — sola lettura, per chi vuole costruirci sopra qualcosa. La
  chiave si vede una volta sola.
- Se sei admin, qui compaiono anche **le visite al sito**, l'**import dal
  Wizards Locator** e la creazione dei **profili dei minori**.
