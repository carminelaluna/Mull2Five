# Segnalare un problema di sicurezza

Il codice di Mull2Five è pubblico, il servizio no: è **in prova**, non ancora
aperto ai negozi. Su `https://mull2five.onrender.com` gira una versione di
collaudo, con pagamenti simulati e dati di prova.

Questo cambia la gravità delle cose, non la loro importanza: un difetto trovato
adesso costa un commit, lo stesso difetto trovato dopo l'apertura costa i soldi
o i dati di qualcuno.

## Come segnalare

**Non aprire una issue pubblica.** Usa la segnalazione privata di GitHub:

> *Security* → *Report a vulnerability*

Va direttamente a chi mantiene il progetto, resta privata finché non è risolta,
e non richiede di scambiarsi indirizzi email.

Se quel canale non ti è accessibile, apri una issue che dica soltanto «ho
trovato un problema di sicurezza, come te lo mando?», senza dettagli.

## Cosa serve in una segnalazione

- cosa hai trovato, in una frase;
- come riprodurlo — richiesta, parametri, ruolo dell'utente;
- cosa ottiene chi lo sfrutta: dati di altri, soldi, accesso a un negozio non suo;
- se l'hai provato sul sito di collaudo o solo leggendo il codice.

Rispondo appena posso. Il progetto lo porta avanti una persona sola, quindi non
prometto tempi che non potrei mantenere.

## Cosa interessa di più

Il modello di questo sito è che **ogni negozio vede solo i propri clienti**.
Quindi contano soprattutto:

- leggere o modificare i dati di un altro negozio;
- ottenere un ruolo che non si ha — judge, capojudge, organizzatore, admin;
- far risultare pagata un'iscrizione che non lo è;
- leggere liste dei mazzi prima della scadenza, o quelle di altri giocatori;
- prendere il posto di un altro account.

## Cosa non è un difetto di sicurezza

- Il primo caricamento lento: il piano gratuito di Render addormenta il
  servizio, e il database si mette in pausa dopo una settimana di inattività.
- `mull2five-staging.onrender.com`: è una copia di prova, con dati anonimizzati,
  tenuta fuori dai motori di ricerca apposta.
- La registrazione accetta il ruolo scelto da chi si iscrive. È voluto **finché
  il servizio è in prova**, ed è già fra le cose da chiudere prima
  dell'apertura ai negozi.

## Difetti già noti

Stanno nel `TODO.md`, pubblico come il resto. Al momento non ce ne sono di
sicurezza: quello che c'era — il webhook PayPal che non verificava la firma — è
stato chiuso il 05/10/2026.

Segnalare un modo di sfruttare qualcosa che non era stato considerato è sempre
utile.
