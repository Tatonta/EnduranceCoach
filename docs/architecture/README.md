# Architettura EnduranceCoach: mappa del codice e confini

Fotografia del codice ispezionato l'8 ottobre 2026, compresi i file di deploy predisposti nel working tree. Hosting pubblico e dominio non sono configurati. Il diagramma descrive ciò che esiste; la pagina **Refactoring proposto** è una proposta, non un refactoring già eseguito.

Apri [endurance-coach.drawio](endurance-coach.drawio) con diagrams.net/draw.io: **File → Apri da → Dispositivo**. È XML non compresso, modificabile, con otto pagine. I disegni vettoriali si possono aprire direttamente e ingrandire:

1. [Sistema attuale](01-sistema-attuale.svg): client, due applicazioni, regole condivise, archivi e vendor.
2. [Layer backend](02-layer-backend.svg): presentazione, trasporto, identità, servizi, dominio e persistenza.
3. [Flusso adattamento](03-flusso-adattamento.svg): review, idoneità, anteprima, conferma e transazione atomica.
4. [API HTTP](04-api-http.svg): endpoint, dati scambiati e confini di autenticazione.
5. [Refactoring proposto](05-refactoring-proposto.svg): porte, repository, UnitOfWork e adapter.
6. [Deploy e isolamento](06-deploy-e-isolamento.svg): processi/worker, database, segreti e ingresso HTTPS da configurare.
7. [Dettagli canonici](07-dettagli-canonici.svg): adapter, contratto di lap/campioni, API per fonte, storage separato, analisi comune e review nativa.
8. [Redis e job proposti](08-redis-proposto.svg): PostgreSQL autorevole, outbox/dispatcher, broker/cache e worker vendor futuri.

Le versioni PNG con gli stessi nomi sono anteprime. Il [catalogo delle API](api-catalog.json) è estratto dal codice Python, non scritto a memoria. Rigenera XML, SVG e catalogo con `python -m scripts.create_architecture_diagrams`.

## Il punto principale: attualmente ci sono due percorsi

**App personale Garmin.** Browser locale, CLI e scheduler richiamano `Coach`, dentro l'app FastAPI `app/main.py`, normalmente sulla porta 8000. Il programma personale è un file JSON; SQLite conserva cache/stato, mentre la sessione Garmin è separata. Questo percorso può leggere Garmin e caricare/schedulare workout attraverso il client personale. Le sue API `/api/*` non implementano login multi-atleta e non sono il backend da esporre su Internet.

**Piattaforma multi-atleta.** Il client iPhone richiama l'app FastAPI `app/platform/main.py`, normalmente sulla porta 8001, usando `/v1/*`. Il server ricava l'atleta dalla sessione Bearer. Piani, attività, evidenze, proposte, sessioni e audit sono nello stesso database della piattaforma, separato dal database personale. Per hosting è previsto PostgreSQL; SQLite serve per sviluppo/test. La piattaforma non legge i token Garmin locali e non sincronizza programmi con gli orologi.

I due percorsi **condividono codice di regole**, non database, sessioni o uno stato globale comune. La UI web personale non è ancora un frontend della piattaforma `/v1`. Il blocco “Regole condivise” rappresenta una libreria importata in ciascuna applicazione, non un terzo servizio HTTP.

Aggiornamento: il percorso personale locale include ora analisi misurata di lap/campioni e un adapter **ChatGPTService**. Dopo Sign in with ChatGPT e consenso all’uso del piano, ChatGPT formula la review su seduta e storico. Le regole condivise nei disegni restano deterministiche e non fanno chiamate LLM; il modello non modifica direttamente il programma. Vedi [review dettagliata e collegamento account](../DETAILED_REVIEW.md). Questo adapter locale non è ancora un servizio ChatGPT multi-atleta ospitato né un’abilitazione App Store.

La home personale parte dal questionario e dall'assistente; il client iOS include Coach e feedback manuali. La piattaforma usa lo schema 3, con profili e dettagli delle attività separati dai riepiloghi. La vista 7 approfondisce i nuovi layer. La vista 8 è una proposta: nessun Redis, dispatcher o worker vendor è attualmente implementato. Vedi [contratto dei dettagli](../CANONICAL_DETAILS.md) e [decisione Redis](../REDIS_DECISION.md).

## Layer attuali e responsabilità

| Layer | Responsabilità | Codice da leggere |
| --- | --- | --- |
| Presentazione iOS | Schermate, stato visualizzato, conferma esplicita; non decide l'idoneità | `ios/AdaptiveCoach/*View*.swift`, `CoachStore.swift` |
| Trasporto iOS | HTTPS, token, JSON e DTO Swift; redirect respinti | `APIClient.swift`, `Models.swift` |
| Adapter locale HealthKit | Lettura autorizzata, normalizzazione in unità SI, anteprima e consenso upload | `HealthImporter.swift`, `HealthEvidence.swift` |
| Sessione dispositivo | Token opaco nel Keychain, legato a origine/account; nessuna password persistita | `SessionVault.swift` |
| API piattaforma | Routing, validazione richiesta, middleware, autenticazione e risoluzione owner | [main.py](../../app/platform/main.py), [schemas.py](../../app/platform/schemas.py) |
| Servizio account | Registrazione/login/logout/delete, Argon2id, digest dei token e rate limit | [security.py](../../app/platform/security.py) |
| Servizio atleta | Piano/versioni, import/dedup, review, anteprima/applicazione, export e audit | [service.py](../../app/platform/service.py) |
| Regole condivise | Associazione piano/attività, consigli, confronto delle corse e generazione dei cambi | [reviewer.py](../../app/services/reviewer.py), [workout_review.py](../../app/services/workout_review.py) |
| Modelli condivisi | Plan/Workout/Step e ActivityRecord; vincoli e unità dei dati | [models.py](../../app/models.py), [activities.py](../../app/integrations/activities.py) |
| Persistenza piattaforma | Sessioni SQLAlchemy, snapshot, transazioni, lock atleta, pool/timeout | [store.py](../../app/platform/store.py), [tables.py](../../app/platform/tables.py) |
| Orchestrazione personale | Refresh, review, scheduler, lock su file, sync e cleanup locali | [coach.py](../../app/services/coach.py), [sync.py](../../app/services/sync.py), [cleanup.py](../../app/services/cleanup.py) |

Dentro il backend questi sono **moduli nello stesso processo Python**, non microservizi isolati da una rete. Il confine HTTP reale è tra client iOS e FastAPI; il confine SQL reale è tra applicazione e database. Il server può avviare più worker, ma ognuno usa gli stessi servizi/modelli e il medesimo database.

## Come comunicano i moduli interni

| Chiamante → destinatario | Contratto attuale | Tipo di comunicazione |
| --- | --- | --- |
| SwiftUI → CoachStore | `refresh()`, `previewAdjustment()`, `applyAdjustment()`, `previewHealth()`, `uploadHealth()` | Metodi Swift asincroni/stato osservabile |
| CoachStore → APIClient | `request<T: Decodable>(path, method, body)` / `raw()` | URLSession; JSON richiesta/risposta |
| CoachStore → SessionVault | `read()`, `write(SessionSecret)`, `clear()` | API Keychain locale |
| HealthImporter → Apple Health | HealthKit queries/read authorization | SDK iOS locale, non HTTP verso un vendor |
| FastAPI → AccountService | `authenticate(token)` / operazioni account | Chiamate Python; ritorna contesto identità |
| FastAPI → AthleteService | `review(athlete_id)`, `preview(athlete_id)`, `apply(athlete_id, proposal_id, expected_version, confirmed)` | Chiamate Python; owner dal server |
| AthleteService → regole | `review_latest_workouts(plan, activities, now)`, `last_workout_review(...)`, `adjusted_plan(plan, now, direction)` | Funzioni Python; strutture validate e snapshot in memoria |
| Servizi → PlatformStore | `read_session()`, `transaction()`, `lock_athlete(session, id)` | Session/ORM SQLAlchemy; query nei servizi |
| PlatformStore → database | Driver sqlite3 oppure psycopg; modelli `ac_*` | SQL, commit/rollback e vincoli del DB |
| Coach locale → ActivitySource | `fetch(now, earliest) -> list[ActivityRecord]` | Protocol Python; oggi adapter Garmin personale |
| SyncService locale → GarminClient | Upload, rilettura/validazione e schedule | Wrapper personale `python-garminconnect`; chiamate cloud |

`ActivitySource` è già un'interfaccia di import. Non esistono ancora analoghe porte astratte per i repository del backend, un `UnitOfWork` separato o l'export multi-vendor. Non ci sono API HTTP tra `AthleteService`, regole e store.

## API pubblicate dal codice della piattaforma

`/health` è pubblico. Login/registrazione accettano credenziali per creare una sessione; registrazione chiusa di default. Le altre route sotto elencate richiedono `Authorization: Bearer <token>`. È un token opaco, non un JWT. Nelle richieste atleta non c'è un `athlete_id` scelto dal client.

| Area | API | Dati / effetto |
| --- | --- | --- |
| Account | `POST /v1/auth/register` | Email, password, timezone; crea account quando abilitato |
| Sessione | `POST /v1/auth/login` | Email/password → `access_token`, `expires_at` |
| Sessione | `POST /v1/auth/logout` | Revoca la sessione corrente |
| Identità | `GET /v1/me` | ID, email e timezone dell'account autenticato |
| Privacy | `GET /v1/me/export` | Solo propri dati, piani, fonti, proposte/evidenze e audit |
| Privacy | `DELETE /v1/me` | Password attuale e `confirmed: true`; cancellazione con cascade |
| Piano | `GET /v1/plan` | `{version, plan}` |
| Piano | `PUT /v1/plan` | `{expected_version, plan}`; conflitto se versione cambiata |
| Cronologia | `GET /v1/plan/history` | Versioni immutabili dei propri piani |
| Attività | `GET /v1/activities` | Paginazione `limit/offset`, fonti e totale |
| Import | `POST /v1/activities/import` | `{ingestion_method: "client_import", activities: [...]}`; batch 1–500 |
| Attività | `DELETE /v1/activities/{provider}/{provider_id}` | Rimuove quel record sorgente solo nel proprio account |
| Review | `GET /v1/review/workout` | Ultima seduta, confronto piano, advice, `program.eligible`, limiti e versione |
| Anteprima | `POST /v1/review/adjustments/preview` | Proposta salvata dal server, cambi esatti, versione e scadenza |
| Conferma | `POST /v1/review/adjustments/{proposal_id}/apply` | `{expected_version, confirmed: true}`; applicazione atomica |
| Capacità | `GET /v1/integrations` | Catalogo e stato; nessuna connessione piattaforma live |
| Schema | `GET /v1/openapi.json` | OpenAPI autenticato; modelli delle richieste |

**ActivityRecord** preserva `source`, `source_activity_id`, sport, nome e timestamp con offset. Usa metri, secondi, secondi/km e bpm; le metriche opzionali mancanti restano mancanti. **Plan** contiene `Workout`, a sua volta contenente `Step`, con durata o distanza e target. La piattaforma normalizza/deduplica le fonti, ma gli import dal client non sono attestazioni verificate dalle API dei vendor.

Le risposte review/proposta sono ancora dizionari Python senza `response_model` esplicito. I DTO Swift e le fixture ne verificano il formato, ma l'OpenAPI non descrive già ogni campo della risposta in modo completo. Tipizzare queste risposte è uno dei miglioramenti di isolamento proposti.

## Dove l'isolamento è già effettivo

- **UI ↔ regole:** iOS riceve `program.eligible`; l'idoneità e il nuovo piano vengono calcolati dal server. Il client non cambia il programma da solo.
- **Atleta ↔ atleta:** identità derivata dalla sessione, scope nelle query, chiavi/vincoli e test di accesso incrociato. È autorizzazione applicativa; non è PostgreSQL Row Level Security.
- **Letture ↔ scritture concorrenti:** snapshot coerenti nelle letture; lock sul record atleta nelle mutazioni. Più worker non possono accettare due volte la stessa proposta.
- **Piano ↔ evidenze ↔ audit:** acceptance dentro una transazione; commit completo o rollback completo. Cambi di dati, versione, data o scadenza invalidano l'anteprima.
- **Personale ↔ piattaforma:** archivi separati; l'immagine backend esclude client/sessioni/dati personali Garmin. Le credenziali del DB possono essere montate come file segreto.

I test coprono questi confini, non una garanzia generale di sicurezza o un test di carico. Il database PostgreSQL reale è stato testato con 31 casi API; iOS compila e passa otto casi di contratto/trasporto in CI. Permessi HealthKit, esperienza UI, firma e device reali restano da verificare.

## Dove l'isolamento è ancora incompleto

`AthleteService` e `AccountService` conoscono SQLAlchemy, sessioni e tabelle concrete. `AthleteService` raccoglie più responsabilità (import, dedup, piano, review/adattamento ed export). `Coach` locale è un orchestratore ampio legato a file, Garmin e scheduler. I modelli di dominio condivisi usano Pydantic; “regole pure” significa assenza di I/O, non assenza di qualunque dipendenza di libreria. Non c'è ancora un sistema durevole di job/webhook e non ci sono adapter OAuth multi-vendor approvati. Le due API `/api` e `/v1` hanno flussi/versionamento diversi.

## Proposta da usare per guidare un refactoring

1. **Estrarre repository e UnitOfWork.** Spostare query/SQLAlchemy fuori dai casi d'uso. Conservare una singola transazione per applicazione del piano/evidenze/audit, senza commit nascosti nei repository.
2. **Tipizzare request e response DTO.** Separare contratto HTTP, contesto autenticato e dati del dominio; aggiornare OpenAPI e fixture/client insieme.
3. **Dividere i casi d'uso.** Import/dedup, lettura review, preview/apply e gestione account, riusando le regole e i test già presenti.
4. **Separare le capacità vendor.** Lettura attività (`ActivitySource`) e pubblicazione workout (`WorkoutPublisher`) sono porte diverse. Aggiungere OAuth, token cifrati, cursori/retry e job durevoli quando esiste accesso autorizzato.
5. **Decidere il ruolo della UI personale.** Mantenerla come strumento locale oppure farne un frontend `/v1`; evitare di mantenere due flussi pubblici diversi per la stessa operazione.

La pagina 5 mostra questa proposta con linee tratteggiate. Non è necessario trasformare subito ogni layer in un microservizio: la separazione delle dipendenze si può ottenere dentro un backend modulare. Un eventuale servizio di generazione linguistica va dietro un adapter e non deve bypassare conferma, regole o transazioni.

## Termini usati nei disegni

- **DTO:** struttura di dati scambiata tra client/API o tra moduli; non contiene necessariamente la logica di business.
- **ORM:** libreria che collega oggetti Python e tabelle SQL; qui è SQLAlchemy.
- **Repository:** interfaccia per leggere/scrivere dati senza far conoscere SQL e tabelle al caso d'uso.
- **UnitOfWork:** coordina un gruppo di operazioni che devono essere confermate o annullate insieme.
- **Porta:** nel refactoring significa interfaccia di codice, non una porta TCP come 8001.
- **Adapter:** implementazione concreta di un'interfaccia, per esempio PostgreSQL o un vendor.
- **Snapshot:** letture riferite allo stesso momento del database, anche mentre un altro worker modifica dati.
- **Monolite modulare:** un'applicazione unica con moduli separati; i layer non richiedono necessariamente server separati.
