# Il back-office

`organizer.html` — riservato a chi ha un account da organizzatore o admin. Un
giocatore che ci arriva trova una spiegazione, non una pagina vuota.

Cinque sezioni in cima: **Eventi**, **Manifestazioni**, **Circuiti**,
**Community**, **Negozio**.

## Eventi

L'elenco dei tuoi tornei, i prossimi sopra e i conclusi in fondo. I conclusi
restano consultabili e non si eliminano: sono lo storico del negozio.

Su ogni scheda: un contatore di avvisi (solo quelli veri, non le note) e le
azioni rapide — Avvia, Regia a parte, Modifica, Duplica, Ripeti, ★ Modello,
Chiudi.

**Nuovo evento** chiede il minimo: nome, gioco, formato (da una tendina, con
"Altro" per i formati di casa), data e ora, luogo e città, posti, quota. Se il
negozio ha delle sedi, ne scegli una e luogo e città li eredita da lì. Fra le
opzioni avanzate c'è anche l'**early bird**: una quota ridotta valida fino a una
data compresa, dopo la quale si torna a quella piena. La pagina pubblica mostra
sempre quella che si paga adesso, ed è la stessa che incassa il banco.

**★ Modello** mette da parte le impostazioni di un torneo col nome che gli dai;
poi "Parti da un modello", in cima a "Nuovo evento", le rimette nel modulo.
Serve dove "Duplica" non arriva: a settembre, quando il torneo di giugno da
copiare non si trova più nell'elenco. La data non la porta: è l'unica cosa che
un modello non può sapere. I modelli sono del negozio, non del singolo.

**Ripeti** crea una serie: ogni settimana, ogni due o ogni mese. Le modifiche
fatte dopo possono andare a tutta la serie o solo alla tappa aperta.

**Importa calendario** carica un foglio di calcolo, un torneo per riga.
L'anteprima parte da sola: ti dice riga per riga cosa succederebbe prima di
importare, e ricaricare lo stesso file non crea doppioni.

### Dentro un evento

Cinque schede: **Regia**, **Giocatori**, **Annunci**, **Staff**,
**Impostazioni**, **Risultati**. Un evento di sola iscrizione non ha Regia né
Risultati, perché non ha turni.

Sopra le schede, accanto a "Pagina pubblica", c'è **▦ QR iscrizione** (finché
l'evento non è concluso). Apre `qr.html?t=<id>`: un foglio con nome, formato,
data, negozio e luogo, e un QR grande. Chi lo inquadra arriva sulla pagina del
torneo con la finestra d'iscrizione già aperta (`event.html?id=<id>&iscriviti=1`);
se non ha fatto l'accesso passa dal login e torna lì. Il foglio si stampa (A4,
solo il foglio, senza menu) o si scarica in PNG o SVG per i social, e c'è
"Copia link". Il QR lo disegna il server
(`/api/tournaments/{id}/registration-qr.svg` o `.png`, pubblico come la pagina
a cui porta) con l'indirizzo del sito (`SITE_URL`): un foglio stampato dallo
staging punta allo staging.

- **Giocatori** — una riga per persona: pagamento, check-in, lista, penalità,
  tag. Da qui si iscrive al banco, si importa da file, si tolgono i non
  paganti, si fanno i pod di draft e le squadre.
- **Annunci** — un messaggio a chi è iscritto, in pagina e via email o push se
  accese. Si può restringere ai portatori di certi tag: vedi sotto.
- **Staff** — chi ti aiuta su *questo* torneo: capojudge (uno solo) e judge.
- **Impostazioni** — tutto il resto: struttura, turni previsti, timer, scadenza
  liste, visibilità di abbinamenti e classifica, domande all'iscrizione, quota
  ed early bird, e i **codici sconto**.
- **Risultati** — classifica, premi consegnati, report ufficiale ed esportazioni.

**I codici sconto** stanno in fondo a Impostazioni, sotto le domande
all'iscrizione. Un codice è di quel torneo: una percentuale *oppure* un importo
(mai tutt'e due), con una scadenza e un numero di usi facoltativi. Chi si
iscrive lo scrive nel modulo, e da lì in poi il codice resta attaccato alla sua
iscrizione: quello che vede scritto è quello che paga, al banco o online.

«Ritira» toglie il codice dalla circolazione. Se non l'aveva ancora usato
nessuno sparisce; se qualcuno l'ha usato **resta, chiuso**, perché cancellarlo
cambierebbe il prezzo a chi si era già iscritto con quello sconto. Chiuso vuol
dire che non ne entrano altri.

## Manifestazioni

Un contenitore di tornei che si svolgono insieme (un weekend, una convention).
Ha una pagina pubblica con il programma raggruppato per giornata, e uno staff
che vale su tutte le tappe.

## Circuiti

Le leghe del negozio: i tornei scelti sommano i punti in **una classifica
sola**, con una pagina pubblica (`series.html?c=<slug>`) se la si vuole.
Una manifestazione raggruppa tornei che si giocano *insieme*; un circuito somma
tornei giocati in giorni diversi, anche per mesi.

**+ Nuovo circuito** chiede nome e regole dei punti, poi si entra a scegliere i
tornei. Dentro un circuito:

- **Tornei del circuito** — quelli che contano, con "Togli": il torneo resta,
  escono solo i suoi punti.
- **Aggiungi tornei** — l'elenco dei tuoi tornei, filtrabile in *Già giocati* e
  *In programma*. Si spuntano e si aggiungono insieme ("Seleziona tutti" per
  prenderli in blocco): i già giocati portano subito i risultati in classifica,
  quelli in calendario contano appena si gioca un turno. Si può fare tutto
  all'inizio o un torneo alla volta, man mano. **Un torneo sta in un circuito
  solo**: se era in un altro, l'elenco lo dice e chiede conferma prima di
  spostarlo. Anche "Duplica" e "Ripeti" lasciano la copia nel circuito
  dell'originale.
- **Classifica** — i primi 20, la stessa della pagina pubblica.
- **Regole e anagrafica** — nome, periodo, descrizione, pagina pubblica, e i
  punti: a vittoria (un bye vale una vittoria), a pareggio, **a tappa giocata**,
  il **bonus torneo vinto**, il **bonus imbattuto** e gli **scarti**, più la
  **soglia di qualificazione** che sulla classifica segna "qualificato".
  Cambiare le regole ricalcola tutto, anche le tappe già giocate.

Ogni tappa dà a ogni giocatore un punteggio: vittorie e pareggi, i punti
presenza, e i due bonus se li ha presi. Il totale è la somma delle tappe.

- **Bonus torneo vinto**: il vincitore di un torneo concluso è chi vince la
  finale se c'è un taglio (top 8, eliminazione diretta), altrimenti il primo in
  classifica con gli spareggi del gioco.
- **Bonus imbattuto**: a chi ha vinto *tutti* i match di un torneo concluso, i
  bye compresi. Basta un pareggio per non prenderlo.
- **Scarti**: "Scarta i peggiori *N* se i tornei sono più di *M*". Quando il
  circuito ha più di *M* tornei giocati, a ognuno si tolgono i suoi *N*
  punteggi di tappa più bassi; una tappa saltata vale 0, quindi è la prima a
  sparire. Ne resta sempre almeno una. Con 0 scarti si somma tutto. In
  classifica la colonna "Scarti" dice quanti punti ha perso ciascuno; V/P/S e
  tappe restano quelli di tutto il circuito.

**Un circuito nuovo parte con le regole della lega del negozio**: 3 a
vittoria, 1 a pareggio, 1 a tappa giocata, 1 di bonus imbattuto, nessun bonus
vincitore, e oltre 4 tornei si scartano i 2 punteggi peggiori. Si cambiano nel
modulo prima di crearlo. I circuiti nati prima del 24/11/2026 hanno bonus
imbattuto e scarti a zero: la loro classifica non è cambiata.

Una tappa conta come giocata se si è giocato almeno un turno: chi è solo
iscritto a un torneo futuro non compare ancora, e un torneo in calendario non
conta per la soglia degli scarti.

**Chiudi circuito** lo segna come concluso e non accetta più tornei (la
classifica resta); "Riapri" lo rimette in corso. **Elimina circuito** lo toglie
del tutto: i tornei restano, liberi. Il circuito lo gestisce chi l'ha creato e
chi fa parte del suo negozio.

## Community

Due cose che riguardano le **persone**, non i singoli tornei.

### I tag

Un tag è un'etichetta che **il tuo negozio** mette ai propri clienti: "Nuovo",
"Habitué", "Gioca solo Commander". Vive dentro il tuo negozio — la stessa
persona può essere "Habitué" da te e sconosciuta altrove.

**Servono un negozio.** I tag li vede e li usa solo chi fa parte dello staff del
negozio a cui appartengono. Chi un negozio non ce l'ha ancora non ha tag: la
scheda Community glielo dice e indica dove aprirlo, e gli annunci vanno a tutti
gli iscritti. I tag creati prima, quando bastava essere organizzatori, seguono
chi li ha creati dentro il negozio che apre.

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
- **Incassi online** — Stripe e PayPal, con la quota della piattaforma. Sui siti
  dove si paga solo al banco (`ONLINE_PAYMENTS_ENABLED=false`, oggi la
  produzione) le caselle "Online Stripe" e "Online PayPal" del torneo non ci sono.
- **Staff del negozio** — titolare e organizzatori: gestiscono *tutti* i tornei
  del negozio, non solo i propri.
- **Chiavi API** — sola lettura, per chi vuole costruirci sopra qualcosa. La
  chiave si vede una volta sola.
- Se sei admin, qui compaiono anche **le visite al sito**, l'**import dal
  Wizards Locator** e la creazione dei **profili dei minori**.
