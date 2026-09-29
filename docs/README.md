# Come funziona Mull2Five

Una guida per parte del sito. Non è la documentazione dell'API (quella è su
`/docs`, generata da FastAPI) e non è il manuale di sviluppo (quello è
`CLAUDE.md`): qui c'è **cosa fa ogni schermata e perché**.

| Guida | Di cosa parla |
|---|---|
| [Il back-office](back-office.md) | Eventi, Manifestazioni, **Community e tag**, Negozio |
| [La regia](regia.md) | La console in sala: turni, tavoli, risultati, timer |
| [Il lato pubblico](pubblico.md) | Cosa vedono i giocatori: ricerca, iscrizione, liste, segnalazioni |
| [I ruoli](ruoli.md) | Chi può fare cosa: giocatore, organizzatore, judge, capojudge, admin |
| [La messa online](hosting.md) | Render, Supabase, variabili d'ambiente, backup e ripristino |

## Le tre parti in due righe

Il **lato pubblico** serve a farsi trovare: ricerca eventi, pagina del negozio,
archivio delle liste. Il **back-office** è dove un negozio prepara e gestisce i
suoi tornei. La **regia** è la schermata che si tiene aperta in sala mentre si
gioca, ed è l'unica pensata per essere usata in piedi.
