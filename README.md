# EnduranceCoach
A ChatGPT live-coach with integration with many different Fitness Watches/Ciclocomputers vendors, to improve aerobic performance and structure a training plan based on your needs

## Garmin Adaptive Coach

Coach Garmin personale locale: FastAPI, HTML/Jinja2, SQLite e APScheduler. Il piano è in `data/workouts.json`; l'app legge attività reali, costruisce workout con step Garmin, verifica la rilettura dopo upload e mantiene un calendario coerente con il piano confermato.

## Avvio su questo computer

Clona il repository e configura un ambiente Python 3.12 o successivo; gli esempi Windows usano `C:\Dev\EnduranceCoach`.

```powershell
cd C:\Dev\EnduranceCoach
.\.venv\Scripts\python.exe run.py
```

Dashboard: **http://127.0.0.1:8000/**. API interattiva: **http://127.0.0.1:8000/docs**.

Il primo ingresso apre il questionario: obiettivo e scadenza, peso/altezza facoltativi, dispositivo, esperienza, migliori tempi, palestra e disponibilità. Dopo il salvataggio la home è il coach AI, con il contesto personale e il collegamento ChatGPT. Funziona anche senza dispositivo. Il pannello operativo precedente è `/dashboard`; un programma esistente viene conservato. [Onboarding, assistente e API del profilo](docs/COACH_ONBOARDING.md).

La home Coach permette anche di registrare durata, sforzo percepito e sensazioni senza orologio. Il feedback entra nello storico e nella review come dichiarazione, senza inventare metriche misurate né attivare un adattamento prestazionale automatico. È disponibile anche nel client iOS: [registro manuale e contratti](docs/MANUAL_FEEDBACK.md).

Review dell'ultimo workout e consigli pratici: **http://127.0.0.1:8000/review**.

La review dettagliata legge lap, step e campioni Garmin, confronta le fasi con il piano, mostra running dynamics, grafico passo/FC e mappa. Il bottone **Continue with ChatGPT** collega il piano ChatGPT dell’atleta senza chiave API e abilita la review professionale sullo storico. [Funzionamento, disponibilità e verifiche](docs/DETAILED_REVIEW.md).

La nuova scheda confronta l'ultima attività con il piano e spiega se mantenerlo. La proposta di adattamento appare solo dopo quattro corse facili comparabili, su almeno sette giorni, con miglioramento continuo ≥6% o rallentamento ≥8%, dati recenti e FC/durata/dislivello compatibili. Sono soglie euristiche: un risultato isolato o dati mancanti non abilitano il cambio. Il popup mostra le modifiche per i prossimi sette giorni; accettarle salva un backup locale e richiede poi test e sync espliciti per Garmin. API: `GET /api/review/workout`, `POST /api/review/adjustment/preview`, `POST /api/review/adjustment/apply`.

È stata introdotta una boundary comune per gli adapter attività (`ActivityRecord` / `ActivitySource`), usata dal refresh Garmin, con unità SI e identità della fonte. `GET /api/integrations` distingue l'adapter locale dalle integrazioni pianificate. L'app resta locale e mono-utente. Architettura proposta, accessi vendor necessari e percorso iOS/App Store: [roadmap produzione](docs/PRODUCTION_ROADMAP.md).

Il backend multi-atleta separato è ora implementato in `app/platform`: autenticazione, piano per account con versioni, import attività, deduplicazione conservativa, review, proposte transazionali, export e cancellazione account. Richiede le dipendenze opzionali `.[platform]` e un database nuovo, separato dai dati Garmin personali. Configurazione, API e limiti verificati: [backend multi-atleta](docs/PLATFORM_API.md). Non è ancora un servizio pubblico, non include connessioni OAuth live e non costituisce una release iOS.

Il client iPhone nativo SwiftUI è ora presente in `ios/AdaptiveCoach.xcodeproj`: Review, Consigli, conferma delle proposte, import piano JSON, anteprima Apple Health con consenso separato all'invio, sessioni nel Portachiavi, export e cancellazione account. [Avvio e verifiche iOS](ios/README.md). La build macOS con Xcode 16.4 e gli otto test nativi passano in [GitHub Actions](https://github.com/Tatonta/EnduranceCoach/actions/runs/37741009818); le prove HealthKit, UI e su dispositivo restano da eseguire. Nessuna app è stata firmata o inviata all'App Store.

Scheda dei migliori tempi: **http://127.0.0.1:8000/performances**.

Mappa dei layer, delle chiamate e delle API: [architettura illustrata](docs/architecture/README.md). Include XML draw.io modificabile con sei viste, disegni SVG/PNG, catalogo delle route estratto dal sorgente e una proposta di refactoring separata dall'architettura attuale.

Salite in bici: **http://127.0.0.1:8000/climbs**.

Se il server è già acceso, usa l'URL: una seconda istanza sulla stessa porta non partirà. Per arrestare l'avvio in primo piano: `Ctrl+C`.

## Installazione da zero

Richiede Python 3.12+; verificato su Windows con Python 3.14.7.

```powershell
cd C:\Dev\EnduranceCoach
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Per riprodurre le versioni verificate, aggiungi `-c requirements-lock.txt` all'ultimo comando. Attivare la venv è facoltativo:

```powershell
.\.venv\Scripts\Activate.ps1
python run.py
```

Se PowerShell impedisce l'attivazione, usa direttamente `.\.venv\Scripts\python.exe` come negli esempi: non serve cambiare le policy di sistema.

Nessun piano personale è incluso. `python -m scripts.create_initial_plan` crea un esempio sintetico soltanto se `data/workouts.json` è assente e si rifiuta di sovrascriverlo. Sostituisci l’esempio prima di qualsiasi sincronizzazione con l’orologio.

## Configurazione

I valori predefiniti sono sufficienti. Per personalizzarli, copia `config/local-environment.example` in `.env`:

```powershell
Copy-Item config/local-environment.example .env
```

| Variabile | Default | Uso |
|---|---|---|
| `COACH_DATA_DIR` | `data` | Directory del piano, database e snapshot; path relativo al progetto |
| `GARMIN_TOKEN_DIR` | `~/.garminconnect` | Sessione persistente fuori dal repository |
| `COACH_TIMEZONE` | `Europe/Rome` | Date delle sessioni e scheduler |
| `COACH_PORT` | `8000` | Porta locale |
| `COACH_SCHEDULER` | `true` | Review periodica ogni due giorni |
| `COACH_STARTUP_REFRESH` | `true` | Lettura Garmin e review all'avvio |

La v1 ascolta su `127.0.0.1`, con un solo worker. Il refresh all'avvio e lo scheduler fanno letture e review; non eseguono cleanup né sync.

## Login Garmin

```powershell
.\.venv\Scripts\python.exe -m app.cli login
```

Prima viene tentata la sessione `~/.garminconnect`. Se assente o rifiutata, la CLI richiede email, password tramite `getpass` ed eventuale MFA anch'esso nascosto. I token vengono salvati nella directory esterna configurata. Il server non richiede mai credenziali nel browser: se la sessione scade indica di usare questo comando nel terminale.

La dipendenza è fissata a `garminconnect[workout]==0.3.17`, la versione già presente e verificata su questo computer. Le sessioni in vecchio formato garth richiedono un nuovo login: [documentazione del progetto python-garminconnect](https://github.com/cyberjunky/python-garminconnect#upgrading-from-02x-garth).

Email, password, MFA, cookie e token non entrano nei file del progetto né nelle risposte API. Le eccezioni Garmin vengono trasformate in messaggi privi di payload sensibili; non attivare il debug HTTP della libreria. `.gitignore` esclude sessioni, `.env`, database, snapshot, log e backup personali. Non copiare la cartella dei token nel repository.

## Uso della dashboard

- **Refresh Garmin** legge attività e VO2max disponibile e aggiorna le metriche. Se il VO2max non è disponibile, viene mostrato l’eventuale valore del piano con la fonte indicata, oppure nessun valore.
- **Run Review** aggiorna Garmin, associa le sessioni in modo conservativo e salva `review_snapshot.json`.
- **Test 1 workout** carica o riusa un singolo template futuro e lo rilegge; non crea una nuova schedulazione.
- **Preview Calendar Cleanup** elenca data, nome, scheduled ID, azione e motivo. Legge tutti i mesi attraversati dal piano e considera esclusivamente `itemType == workout` nell'intervallo prima/ultima data.
- **Apply Calendar Cleanup** si abilita dopo una preview con rimozioni e richiede conferma nella UI. Una preview scade dopo 15 minuti e si invalida se cambia piano o calendario. Un'esecuzione parziale richiede una nuova preview.
- **Sync Plan** richiede un test valido sul piano corrente e conferma del risultato. Crea o riusa i workout mancanti, verifica le fasi e schedula soltanto quelli futuri.
- **Modifica JSON** valida e salva il piano, conservandone una copia precedente in `data/backups`. Dopo un cambiamento occorre ripetere test e preview.

La pulizia usa solo `unschedule_workout()`. Conserva attività registrate, eventi e template nella libreria, inclusi quelli di versioni precedenti. I workout protetti di Garmin Coach possono essere rifiutati da Garmin: l'operazione si interrompe e mostra lo stato parziale, senza chiamare endpoint di cancellazione template.

## CLI

I seguenti comandi funzionano anche senza attivare la venv sostituendo `python` con `.\.venv\Scripts\python.exe`:

```powershell
python -m app.cli login
python -m app.cli validate-plan
python -m app.cli activities
python -m app.cli review
python -m app.cli test-workout
python -m app.cli test-workout --id oct-07
python -m app.cli cleanup --preview
python -m app.cli cleanup --apply
python -m app.cli sync
python -m app.cli serve
```

`cleanup --apply` rigenera e stampa la preview prima di richiedere la parola `CONFERMO`. `sync` richiede la stessa parola dopo aver mostrato il test verificato. In una shell non interattiva entrambi si rifiutano di applicare mutazioni senza conferma.

Flusso consigliato: login → review → test singolo → preview → cleanup confermato → sync confermata. La sync gestisce le vecchie versioni già tracciate dal coach; la pulizia con preview gestisce gli altri piani e i duplicati preesistenti.

## Modificare il piano

La fonte di verità è **solo `data/workouts.json`**. Lo script in `legacy/` conserva la precedente implementazione e non viene eseguito dalla v1; il suo piano personale è escluso dal repository.

È possibile modificare il file con un editor oppure tramite dashboard o `PUT /api/plan`. Mantieni stabile `id` quando cambi contenuto o data di una sessione: serve a collegare la nuova versione alla vecchia schedulazione. Per doppie sessioni assegna ID e nomi distinti. Aggiungere, eliminare o cambiare ID richiede una preview cleanup per riconciliare le vecchie voci.

Esempio di workout strutturato:

```json
{
  "plan_name": "10K Build",
  "workouts": [{
    "id": "threshold-01",
    "date": "2026-10-06",
    "name": "Threshold 3x8",
    "sport": "running",
    "estimated_duration_min": 55,
    "quality": true,
    "description": "Solo se recuperato",
    "steps": [
      {"type": "warmup", "duration_min": 15},
      {"type": "repeat", "iterations": 3, "steps": [
        {"type": "interval", "duration_min": 8, "target": {"type": "pace", "slow": "4:18", "fast": "4:12"}},
        {"type": "recovery", "duration_min": 2}
      ]},
      {"type": "cooldown", "duration_min": 10}
    ]
  }]
}
```

- Sport: `running`, `cycling`, `rest`, `manual`. Rest e manual restano locali senza step Garmin.
- Step: `warmup`, `run`, `interval`, `recovery`, `cooldown`, `repeat`.
- Ogni step eseguibile ha **una sola** misura positiva: `duration_s`, `duration_min` oppure `distance_m`.
- I repeat richiedono `iterations` intero e sotto-step. I repeat annidati sono esclusi nella v1.
- Target passo: `{"type":"pace","slow":"4:18","fast":"4:12"}` in min:sec/km. Il builder converte in m/s con il limite lento più basso.
- Target FC: `{"type":"hr_zone","zone":2}`, zone 1–5 configurate nel profilo Garmin. Per la bici usa zone FC; il passo/km è rifiutato.
- Gli allunghi non hanno un target GPS rigido. Ogni recupero del repeat viene eseguito, incluso quello dell'ultima ripetizione.
- `estimated_duration_min` è una stima; le condizioni reali di fine step sono le durate/distanze negli step.
- `quality: true` abilita indicazione di qualità e valutazione conservativa delle sessioni.
- Campi sconosciuti, ID duplicati, passi invertiti, durate ambigue e numeri non finiti vengono rifiutati.

Il generatore produce un esempio sintetico con corsa, bici, riposo e step a tempo/distanza. Serve per verificare il software; non costituisce una prescrizione personale.

## Verifica Garmin e idempotenza

Dopo ogni upload viene chiamato `get_workout_by_id`. Il confronto verifica sport, segmenti, conteggio e ordine globale degli step, DTO eseguibili e repeat, iterazioni, durata/distanza, tipo di target, entrambi i limiti passo e zona FC. Un mismatch blocca la schedulazione.

SQLite conserva `plan_workout_id`, `garmin_workout_id`, `scheduled_workout_id`, data, hash JSON, stato e ultimo sync. Il template contiene un marcatore `[GAC:local:<hash>]`, utile a ritrovare un upload dopo perdita dello stato. Il nome da solo non prova equivalenza: i template preesistenti vengono riletti e verificati prima del riuso.

La sync legge il calendario reale prima di schedulare e dopo ogni nuova schedulazione. Se cambia una sessione futura già tracciata, verifica la nuova versione prima di deschedulare la vecchia. Un journal SQLite conserva il riferimento precedente anche durante un'interruzione. I template precedenti restano nella libreria.

Timeout o risposte ambigue di upload/schedule producono stato `upload_uncertain`/`schedule_uncertain`: il sistema cerca la voce reale e blocca un ulteriore invio se non la vede. Non forzare cancellando il database: prima verifica Garmin. Il lock condiviso tra processi serializza CLI, API e scheduler.

## Review e snapshot ChatGPT

`data/review_snapshot.json` viene scritto atomicamente e contiene attività normalizzate, piano, associazioni, riepilogo sette giorni, flag, raccomandazioni e limiti interpretativi. Distanze in **metri**, durate in **secondi**, passo in **secondi/km**, FC in bpm; le unità sono dichiarate nel file.

Status: `completed`, `completed_modified`, `substituted`, `missed`, `pending`. Un'attività viene usata al massimo una volta. La review richiede giorno e sport compatibili, durata plausibile e, per la qualità, evidenza nel nome o nel workout ID. Più candidati equivalenti non vengono associati automaticamente. Una corsa in sostituzione della bici viene riconosciuta solo dove l'alternativa è esplicitamente prevista.

La giornata corrente senza attività resta pending. Le sessioni rest già passate sono annotate come riposo previsto non misurabile; quelle manuali non verificate sono segnalate come tali. `missed` significa che non c'è un'esecuzione associabile nei dati disponibili, non una certezza su ciò che l'atleta ha fatto.

Flag implementati: `HIGH_FATIGUE` (proxy da durata/carico recente), `MISSED_QUALITY`, `HIGH_VOLUME`, `LOW_RECOVERY`, `SUBSTITUTED_SESSION`. Non si deducono `OVERPERFORMED_INTERVALS` o `UNDERPERFORMED_INTERVALS` dal passo medio: richiedono analisi dei lap. L'associazione di una sessione di qualità non dimostra che ogni intervallo sia stato rispettato; `interval_compliance` resta `unverified`.

## Scheduler

APScheduler 3.x esegue lettura attività e review ogni due giorni. Le scadenze sono conservate in SQLite e una review scaduta viene recuperata all'avvio. Coalescing e singola istanza evitano esecuzioni sovrapposte. Una review manuale riprogramma la successiva a due giorni.

Funziona finché il server è acceso. Il PC spento o il processo terminato non consentono l'esecuzione; al riavvio viene comunque effettuata la lettura iniziale. Nessuna modifica automatica del piano, cleanup o schedulazione viene eseguita dal job. `/api/health` espone prossima scadenza e ultimo errore sanitizzato.

Il job aggiorna anche i migliori tempi e le salite in bici, riutilizzando i dettagli già analizzati.

## Best performances — dati Garmin

La scheda **Best performances** mostra 400 m, 800 m, 1 km, 1.500 m, miglio, 2 km, 3 km, 2 miglia, 5 km, 10 km, 15 km, 10 miglia, 20 km, mezza maratona, 30 km e maratona. Ogni riga include miglior tempo, passo, data, attività Garmin, fonte e link alla relativa attività Garmin Connect.

La lettura considera tutto lo storico corsa accessibile nell'account Garmin, con paginazione (limite 10.000 corse). I record e i best split Garmin hanno priorità. Per le distanze non esposte da Garmin il sistema cerca il tratto più veloce nei campioni distanza/tempo trascorso, con interpolazione. Pause all'interno del tratto contano; campioni impossibili, salti GPS e contatori incoerenti separano il file in tratti, e nessun tempo calcolato attraversa quelle interruzioni. Questi sono migliori tratti di allenamento, non necessariamente risultati in gara o record certificati. Il confronto non usa il passo medio dell'intera attività per inventare un tempo su una distanza più breve. Una distanza senza campioni sufficienti resta senza tempo.

Sono state lette tutte le 22 corse presenti nell'account, dal 6 luglio 2026. Il tempo Garmin del tratto 10 km è 41:15; può differire dal tempo 41:27 dell'intera attività da 10,03 km. La tabella espone copertura e dati mancanti, invece di presentare una scansione parziale come completa.

La scheda usa esclusivamente Garmin Connect. Non richiede un abbonamento Strava, una app API Strava o l'associazione di account esterni.

API aggiuntive: `GET /api/performances`, `POST /api/performances/refresh`.
CLI aggiuntiva: `python -m app.cli performances`. Snapshot locale: `data/best_performances.json`.

## Salite in bici — Climbfinder e Garmin

La scheda **Salite in bici** apre con una heatmap interattiva dei percorsi completati. Il colore indica il numero di passaggi (verde 1, arancio 2–3, rosa 4+). Il passaggio del mouse mostra nome, variante, lunghezza, dislivello, quota di arrivo, profilo Garmin, miglior tempo e data. Clic, tastiera e il pulsante “Sulla mappa” aprono gli stessi dettagli con link Garmin e Climbfinder. Filtri per paese, regione, provincia e nome aggiornano sia mappa sia schede. La rotella ingrandisce/riduce la mappa quando il puntatore è sopra di essa; fuori dalla mappa scorre la pagina. Il pulsante “Schermo intero” espande la mappa a tutta la finestra, mantenendo filtri e dettagli; si esce con lo stesso pulsante o Esc. Gli aggiornamenti periodici conservano zoom, filtri e popup quando i dati non cambiano.

**Le pendenze generiche non vengono più considerate salite.** Il riferimento è il catalogo locale Climbfinder, con nomi e varianti delle sue pagine pubbliche. Partenza e arrivo vengono proiettati sulla traccia Garmin entro 60 m; direzione e lunghezza devono essere compatibili (8% rispetto alla distanza ufficiale Climbfinder, che può essere maggiore della geometria semplificata). Il percorso viene confrontato in entrambe le direzioni, con campioni ogni 100 m entro 60 m dalla strada. Piccoli buchi GPS (massimo 150 m, con posizione e tempo compatibili) non spezzano la salita; le soste con deriva del GPS conservano il tempo trascorso, senza interpolare i salti del segnale. È richiesta una corrispondenza di almeno l’85% dei campioni in entrambe le direzioni: le eccezioni devono trovarsi vicino a salti GPS o a tratti ricostruiti perfettamente rettilinei che terminano con una riacquisizione del segnale. Questi tratti hanno un limite di 2 km; una strada rettilinea da sola non basta. La scheda e la mappa indicano **GPS parziale**, percentuale di corrispondenza e tempo stimato. Tratti parziali, grandi buchi di distanza e deviazioni senza queste evidenze vengono esclusi. Le varianti rimangono distinte; sullo storico personale sono stati verificati Stelvio e Gavia da Bormio, Torri di Fraele (ricercabile anche come Laghi di Cancano) e Mortirolo via Monno, escludendo la Recta Contador. Il profilo e i tempi provengono esclusivamente da Garmin, mentre lunghezza, ascesa e quota di arrivo sono i dati Climbfinder. Ogni variante conserva tutti i passaggi e il migliore, compresi più passaggi nella stessa uscita. Il tempo trascorso **include le soste** ed è una stima GPS, non un cronometraggio certificato. La velocità media (km/h), mostrata nelle schede, nei dettagli sulla mappa e in ogni tentativo, usa la distanza Garmin tra gli stessi estremi e il tempo trascorso, comprese le soste; non usa la distanza nominale Climbfinder né la velocità media dell’intera uscita.

Il catalogo personale è `data/climbfinder-catalog.json`: un catalogo locale importato dall’utente per uso autorizzato. Il numero di percorsi e le aree coperte sono visibili nella scheda; non è il catalogo mondiale. I dati Climbfinder rimangono nella cartella privata ignorata da Git, non nel pacchetto distribuibile: le [condizioni Climbfinder](https://climbfinder.com/it/termini) prevedono una specifica eccezione per l’uso personale. Non vengono copiate recensioni, foto o testi descrittivi.

L’importazione in blocco usa il servizio vettoriale pubblico dichiarato dal codice della mappa: [TileJSON Climbfinder](https://pmtiles.climbfinder.com/climbs.json), con tile MVT `https://pmtiles.climbfinder.com/climbs/{z}/{x}/{y}.mvt`. Questo servizio risponde senza login o chiave. L’endpoint REST degli elenchi `uphill.climbfinder.com/v2/climbs` invece risponde HTTP 403 e richiede esplicitamente una API key: l’importatore non tenta di aggirarlo e non apre singole pagine HTML.

```powershell
# Aree predefinite: Lombardia e dintorni, Sicilia
.venv\Scripts\python.exe -u -m app.cli import-climbs
# Estensione ad un’altra area: ovest,sud,est,nord
.venv\Scripts\python.exe -u -m app.cli import-climbs --bbox "6.6,43.7,8.4,45.3"
# Dopo l’importazione, ricalcola i tempi sui dati Garmin già in cache
.venv\Scripts\python.exe -m app.cli climbs
```

I tile vengono decodificati con `mapbox-vector-tile` e conservati in `data/climbfinder-tiles/`; un’interruzione lascia il catalogo precedente e consente di riprendere usando la cache. `--refresh` aggiorna anche le risposte già salvate. Le linee divise tra tile vengono unite solo se condividono vertici in ordine. Estremi tagliati, frammenti disconnessi, distanza incompatibile (8%) o arrivo incoerente vengono esclusi. Le quote mancanti nei punti raggruppati della vista generale vengono recuperate dai soli tile di dettaglio necessari. Le geometrie della mappa sono semplificate e quantizzate: i tempi rimangono stime GPS. Le importazioni con zoom 12–14 possono aggiornare geometrie meno dettagliate solo se la nuova linea supera tutti i controlli; in caso di frammenti incompleti vengono conservati il percorso precedente, il suo link e i nomi locali. Le aree già importate restano nella copertura del catalogo; i nomi includono le varianti italiane del servizio. Ogni importazione è limitata a 512 tile di base; per estensioni grandi si procede per aree, senza dichiarare completo il catalogo mondiale. Nessuna coordinata privata Garmin viene usata nelle richieste.

Formato del catalogo: oggetto con `source`, `imported_at`, `regions`, `index_count` e `rows`. Ogni riga contiene `id` (es. `cf-123`), `name`, `source_url` (pagina HTTPS Climbfinder oppure mappa con UUID verificato), `path` (lista di coppie latitudine/longitudine in direzione di salita), `distance_m`, `gain_m`, `summit_m`. Gli ID devono essere univoci; nomi, coordinate e numeri finiti sono validati. Sostituire il file completo in modo atomico, poi premere “Aggiorna salite”. Nuovi percorsi vengono confrontati anche con le tracce già in cache. In assenza del catalogo non vengono inventate salite né riproposti i vecchi risultati generici.

La cache SQLite `cycling_trace_cache` conserva le tracce complete delle uscite bici; il primo recupero è incrementale e riprendibile. La lettura Garmin copre tutto lo storico accessibile, con paginazione e limite di 10.000 uscite. Una modifica dell’attività invalida la sua cache; le uscite prive di dati utilizzabili vengono segnalate. Lo scheduler ricalcola il confronto ogni due giorni usando il catalogo locale, senza chiamare Climbfinder. Le tue tracce GPS non vengono inviate a Climbfinder o a un geocoder.

I confini Natural Earth 5.1.1 (public domain, conservati in `app/assets`) assegnano paese, regione e provincia al punto intermedio del percorso. Possono essere approssimati vicino ai confini. La mappa usa Leaflet 1.9.4, incluso localmente con licenza BSD-2-Clause, e lo sfondo OpenStreetMap con attribuzione visibile. Le sole tessere della vista corrente vengono richieste dal browser e conservate dalla sua normale cache; niente scaricamenti massivi. Lo sfondo richiede Internet; percorsi e dettagli restano disponibili se non si carica. [Politica delle tessere OSM](https://operations.osmfoundation.org/policies/tiles/).

## API

| Metodo | Endpoint | Funzione |
|---|---|---|
| GET | `/api/health` | Stato locale e scheduler |
| GET | `/api/activities/recent` | Cache attività, `?limit=20` |
| POST | `/api/activities/refresh` | Lettura Garmin |
| GET / PUT | `/api/plan` | Lettura / sostituzione validata piano |
| POST | `/api/plan/test` | Test singolo, body `{}` oppure `{"workout_id":"oct-07"}` |
| POST | `/api/plan/sync` | Sync dopo test, body `{"confirmed":true}` |
| POST | `/api/calendar/cleanup/preview` | Preview persistita con ID e scadenza |
| POST | `/api/calendar/cleanup/apply` | Body `{"preview_id":"…","confirmed":true}` |
| GET | `/api/review/latest` | Ultimo snapshot persistito |
| POST | `/api/review/run` | Lettura Garmin + review |
| GET | `/api/dashboard/summary` | Metriche, piano, flag, stato sync |

Esempio di lettura in PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/plan
```

API e CLI condividono `Coach` e i service layer. Per il futuro MCP si possono esporre letture, replace plan, preview, apply e sync usando gli stessi servizi e mantenendo le conferme. SQLite include `user_id`; un futuro multiutente richiederà autenticazione, configurazioni/token per atleta e directory dati separate. La v1 non è un endpoint MCP remoto e non include autenticazione web per uso pubblico.

## Test e controlli

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests scripts run.py
.\.venv\Scripts\python.exe -m pip check
```

I test usano Garmin simulato e directory temporanee. Un fixture vieta esplicitamente l'istanza Garmin reale. Coprono parsing, validazione, pace conversion, repeat, builder running/cycling/distance, mismatch post-upload, hash, calendario, duplicati, scope cleanup, conferme, preview scadute/modificate, idempotenza, perdita stato, versionamento e timeout, review, login/MFA, API e scheduler.

La suite estesa include best effort per distanza, finestre con pause/interpolazione, salti GPS, cache storico, link Garmin, catalogo Climbfinder, riconoscimento di percorsi completi e varianti, confronto sullo stesso percorso, soste, esclusione di strade parallele, confini offline e verifica delle API senza integrazioni esterne: **79 test passati**. La versione Starlette installata segnala un avviso di deprecazione del suo adapter httpx per i test; la suite passa.


Le verifiche su account Garmin reali richiedono accesso autorizzato e restano locali. Il repository include solo codice e fixture sintetiche, non prove di workout personali o stato del calendario.

## Struttura

```text
app/
  main.py, config.py, db.py, models.py, cli.py
  garmin/       client, attività, builder/validazione, calendario
  services/     planner, sync, cleanup, reviewer, performances, climbs, geography, scheduler
  api/          attività, piano, calendario, review, performances, climbs
  templates/    dashboard.html, performances.html, climbs.html
  static/       style.css, dashboard.js, performances.js, climbs.js
  assets/       confini amministrativi Natural Earth (pubblico dominio)
data/
  workouts.json             fonte di verità
  coach.sqlite3             cache, stato, journal, scadenze
  state.json                export stato sync
  review_snapshot.json      export review per ChatGPT
  cleanup_preview.json      ultima preview
  test_workout.json          prova di verifica singola
  best_performances.json     migliori tempi e provenienza
  cycling_climbs.json        salite Climbfinder completate e migliori passaggi
  climbfinder-catalog.json   catalogo personale di percorsi nominati (privato)
tests/                       suite offline
scripts/create_initial_plan.py
legacy/                      file originali conservati
run.py, pyproject.toml, requirements-lock.txt, config/local-environment.example, .gitignore
```

## Troubleshooting

- **Porta occupata:** apri la dashboard già attiva o cambia `COACH_PORT` in `.env` e riavvia.
- **Login richiesto:** esegui la CLI `login` in un terminale interattivo, poi Refresh Garmin. Non incollare credenziali in chat o nei file.
- **Garmin non disponibile / rate limit:** attendi e riprova una singola lettura; non usare loop di login. Cache e snapshot rimangono disponibili.
- **Piano non valido:** `validate-plan` oppure editor UI; controlla durata unica, formato passo, sport, ID e nomi di doppie sessioni.
- **Workout diverso dopo upload:** nessuna schedulazione eseguita. Controlla fasi e target su Garmin, modifica il piano se necessario e ripeti il test. Non creare upload ripetuti per aggirare l'errore.
- **Preview cambiata/scaduta:** genera una nuova preview, rileggila e riconferma.
- **Sync parziale o incerta:** controlla calendario/libreria Garmin; riprova solo dopo che la voce è visibile. Se non esiste realmente, il checkpoint locale incerto richiede riconciliazione manuale prima di un nuovo invio.
- **Un'altra operazione è in corso:** attendi che finisca la CLI, la review o la richiesta della dashboard.
- **VO2max assente:** fonte iniziale chiaramente indicata; non blocca attività e review.
- **Metriche o associazioni incomplete:** attività lette con paginazione, massimo 2.000 nell'intervallo. Il superamento blocca la review incompleta; l'analisi dettagliata di lap, HRV, sonno e readiness è un'evoluzione futura.
- **L’orologio Garmin non mostra il workout:** prima verifica il calendario su Connect e sincronizza l'orologio con Garmin Connect; questa v1 crea/schedula sul cloud, non invia direttamente al dispositivo.

Conserva una copia privata di `data/workouts.json`, `coach.sqlite3` e della sessione esterna; snapshot e log possono contenere dati personali di allenamento e non sono da pubblicare.
