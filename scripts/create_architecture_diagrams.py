"""Generate editable draw.io XML and SVG diagrams of the inspected architecture."""

import ast
import html
import json
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "architecture"
COLORS = {
    "client": ("#edf3ff", "#5972ae"),
    "service": ("#eff8f7", "#497d76"),
    "domain": ("#f3effb", "#8063aa"),
    "store": ("#f1f6e9", "#718544"),
    "planned": ("#fff5e5", "#a77d35"),
    "note": ("#f6f7f9", "#9da7b4"),
}


@dataclass
class Node:
    id: str
    title: str
    lines: list[str]
    x: int
    y: int
    w: int
    h: int
    kind: str = "service"


@dataclass
class Edge:
    source: str
    target: str
    label: str = ""
    points: list[tuple[int, int]] = field(default_factory=list)
    planned: bool = False


@dataclass
class Page:
    slug: str
    title: str
    subtitle: str
    width: int
    height: int
    nodes: list[Node]
    edges: list[Edge] = field(default_factory=list)


def pages():
    return [
        Page("01-sistema-attuale", "Sistema attuale: due percorsi separati", "Frecce = chiamate; verde/blu/viola = codice presente; tratteggio = parte futura. Nessun hosting pubblico.", 1260, 1090, [
            Node("health", "Apple Health sul telefono", ["SDK HealthKit • sola lettura", "Dati effettivamente disponibili e autorizzati"], 70, 110, 340, 110, "client"),
            Node("ios", "App iPhone · SwiftUI", ["Review / Consigli / Piano / Account", "CoachStore + APIClient + SessionVault", "HealthImporter: anteprima + consenso invio"], 70, 270, 340, 135, "client"),
            Node("web", "Browser locale + CLI", ["HTML/Jinja2 + JavaScript", "app/templates, app/static, app/cli.py", "Questa UI NON usa il backend /v1"], 825, 270, 340, 135, "client"),
            Node("platform", "Backend multi-atleta", ["FastAPI · app/platform/main.py", "API /v1/* · autenticazione Bearer", "AccountService / AthleteService", "Nessuna connessione diretta ai vendor"], 70, 500, 340, 160),
            Node("local", "App Garmin personale", ["FastAPI · app/main.py · API /api/*", "Coach: review, refresh, sync, cleanup", "APScheduler + lock su file", "Uso locale mono-atleta, senza login web"], 825, 500, 340, 160),
            Node("engine", "Regole condivise", ["models.py + ActivityRecord", "reviewer.py", "workout_review.py", "Regole deterministiche; nessun LLM", "È una libreria, non un terzo server"], 475, 500, 285, 210, "domain"),
            Node("platformdb", "Archivio della piattaforma", ["PlatformStore → SQLAlchemy", "PostgreSQL per hosting; SQLite nei test", "Account, piani versionati, attività", "Proposte, sessioni e audit per atleta"], 70, 775, 340, 150, "store"),
            Node("localdb", "Archivio personale separato", ["data/coach.sqlite3 + workouts.json", "Cache, snapshot e prove di sync", "Sessioni Garmin fuori dal repository", "Non viene importato nella piattaforma"], 825, 775, 340, 150, "store"),
            Node("future", "Integrazioni ancora da implementare", ["COROS · Suunto · Fitbit/Google Health · Amazfit · Xiaomi", "OAuth approvato, token cifrati, worker/webhook, export workout", "Apple Health è un ponte locale, non un'API diretta del vendor"], 70, 980, 690, 110, "planned"),
            Node("garmin", "Garmin Connect personale", ["GarminClient / python-garminconnect", "Lettura attività + upload/schedule locali"], 825, 980, 340, 110),
        ], [
            Edge("health", "ios", "SDK locale", [(240, 220), (240, 270)]),
            Edge("ios", "platform", "HTTPS · JSON · Bearer", [(240, 405), (240, 500)]),
            Edge("web", "local", "HTTP localhost:8000 / chiamate CLI", [(995, 405), (995, 500)]),
            Edge("platform", "engine", "Python", [(410, 560), (475, 560)]),
            Edge("local", "engine", "Python", [(825, 610), (760, 610)]),
            Edge("platform", "platformdb", "SQL/ORM", [(240, 660), (240, 775)]),
            Edge("local", "localdb", "SQL + file locali", [(995, 660), (995, 775)]),
            Edge("local", "garmin", "HTTPS cloud", [(1165, 580), (1200, 580), (1200, 1025), (1165, 1025)]),
        ]),
        Page("02-layer-backend", "Layer del backend multi-atleta", "Confini logici nello stesso processo Python. L'HTTP separa app iPhone e backend; i servizi dipendono ancora dall'ORM.", 1400, 1070, [
            Node("ui", "Presentazione e stato iOS", ["SwiftUI Views → CoachStore", "Nessuna decisione autonoma sul piano", "Il bottone segue program.eligible"], 70, 130, 370, 135, "client"),
            Node("httpclient", "Trasporto iOS", ["APIClient · URLSession ephemeral", "DTO Swift + encoding/decoding JSON", "HTTPS; redirect respinti"], 535, 130, 345, 135, "client"),
            Node("vault", "Sessione sul dispositivo", ["SessionVault → Keychain", "Token opaco legato a account/origine", "Password non persistita"], 1020, 130, 310, 135, "store"),
            Node("api", "API e identità", ["app/platform/main.py", "FastAPI routes + middleware", "HTTPBearer → identity()", "Owner determinato dal server"], 535, 375, 345, 170),
            Node("schema", "Contratti di ingresso", ["platform/schemas.py · Pydantic", "PlanWrite / ActivityImport", "ProposalAcceptance / AccountDeletion", "StrictModel: rifiuta campi extra"], 1020, 375, 310, 170, "domain"),
            Node("accounts", "Servizio account", ["AccountService · security.py", "Register/login/logout/delete", "Argon2id + digest sessioni + rate limit", "Query SQLAlchemy dirette"], 70, 640, 370, 155),
            Node("athletes", "Servizio atleta", ["AthleteService · service.py", "Piano, import, dedup, review, proposal", "Scope atleta + versioni + audit", "Query SQLAlchemy dirette"], 535, 640, 345, 155),
            Node("rules", "Dominio condiviso", ["Plan / Workout / Step / ActivityRecord", "review_latest_workouts()", "last_workout_review()", "adjusted_plan()", "Nessun LLM, DB o vendor"], 1020, 625, 310, 185, "domain"),
            Node("store", "Persistenza e transazioni", ["PlatformStore · store.py", "transaction() / read_session()", "lock_athlete() · pool e timeout", "Non è ancora un repository astratto"], 535, 905, 345, 145, "store"),
            Node("tables", "Schema SQL", ["tables.py → 8 tabelle ac_*", "FK/cascade, indici e chiavi composte", "PostgreSQL / SQLite", "Autorizzazione applicativa, non RLS"], 1020, 905, 310, 145, "store"),
            Node("coupling", "Punto di refactoring", ["I servizi conoscono Session e tabelle.", "Estrarre repository/UnitOfWork rende", "il dominio e i casi d'uso più isolati."], 70, 905, 370, 145, "planned"),
        ], [
            Edge("ui", "httpclient", "metodi Swift", [(440, 220), (535, 220)]),
            Edge("ui", "vault", "read/write sessione", [(255, 130), (255, 110), (1175, 110), (1175, 130)]),
            Edge("httpclient", "api", "HTTP JSON /v1/*", [(708, 265), (708, 375)]),
            Edge("api", "schema", "valida body", [(880, 460), (1020, 460)]),
            Edge("api", "accounts", "auth + identity", [(535, 495), (255, 495), (255, 640)]),
            Edge("api", "athletes", "identity.id", [(708, 545), (708, 640)]),
            Edge("athletes", "rules", "funzioni Python", [(880, 715), (1020, 715)]),
            Edge("accounts", "store", "sessioni / SQLA", [(255, 795), (255, 865), (610, 865), (610, 905)]),
            Edge("athletes", "store", "ORM + transazione", [(780, 795), (780, 905)]),
            Edge("store", "tables", "driver SQL", [(880, 990), (1020, 990)]),
        ]),
        Page("03-flusso-adattamento", "Flusso: review → proposta → conferma", "La UI visualizza; il server decide e ricontrolla. Nessuna modifica automatica e nessun invio al watch in questo backend.", 1400, 1320, [
            Node("read", "1 · Leggi l'ultima review", ["GET /v1/review/workout", "Piano + attività + regole → advice e program.eligible"], 380, 115, 660, 105),
            Node("eligibility", "2 · Trend realmente idoneo?", ["4 corse facili comparabili su almeno 7 giorni; dati recenti", "Progresso ≥6% oppure rallentamento ≥8%; soglie euristiche", "Ogni passaggio ≥1%; FC, durata e terreno simili"], 380, 290, 660, 130, "domain"),
            Node("keep", "NO · Mantieni il programma", ["Nessun bottone di adattamento", "Consigli pragmatici e limiti dei dati"], 50, 465, 270, 130, "note"),
            Node("preview", "3 · Chiedi un'anteprima", ["POST /v1/review/adjustments/preview", "Salva proposta con owner, base_version, evidence_hash e scadenza 10 min"], 380, 495, 660, 110),
            Node("confirm", "4 · Mostra le modifiche e chiedi conferma", ["Sheet SwiftUI: sedute, step, durate e ripetizioni esatte", "Annullare non cambia il piano; nessuna apertura automatica"], 380, 680, 660, 110, "client"),
            Node("apply", "5 · Accetta esplicitamente", ["POST /v1/review/adjustments/{proposal_id}/apply", "Body: expected_version + confirmed=true"], 380, 865, 660, 105),
            Node("transaction", "6 · Verifica e applica nella stessa transazione", ["lock_athlete → verifica owner, scadenza, versione, hash e idoneità", "PlanVersion + last_adjustment + audit + proposta consumata", "COMMIT completo oppure ROLLBACK completo"], 380, 1045, 660, 130, "store"),
            Node("reject", "409 · Proposta non più valida", ["Dati/piano cambiati o scadenza", "Aggiorna e genera nuova anteprima"], 1080, 1045, 280, 130, "note"),
            Node("result", "7 · Ricarica piano e review", ["Nuova versione; evidenze consumate non riutilizzabili", "vendor_sync = not_implemented"], 380, 1210, 660, 90),
        ], [
            Edge("read", "eligibility", "calcolo server", [(710, 220), (710, 290)]),
            Edge("eligibility", "keep", "NO", [(380, 355), (185, 355), (185, 465)]),
            Edge("eligibility", "preview", "SÌ + click utente", [(710, 420), (710, 495)]),
            Edge("preview", "confirm", "JSON proposta", [(710, 605), (710, 680)]),
            Edge("confirm", "apply", "conferma utente", [(710, 790), (710, 865)]),
            Edge("apply", "transaction", "request autenticata", [(710, 970), (710, 1045)]),
            Edge("transaction", "reject", "incoerente", [(1040, 1110), (1080, 1110)]),
            Edge("transaction", "result", "successo", [(710, 1175), (710, 1210)]),
        ]),
        Page("04-api-http", "API tra app iPhone e backend", "Trasporto: HTTPS + JSON. Bearer opaco sulle route atleta. Registrazione/login e /health non richiedono una sessione.", 1400, 1040, [
            Node("auth", "Autenticazione", ["POST /v1/auth/register · email/password/timezone", "POST /v1/auth/login → access_token + expires_at", "POST /v1/auth/logout · revoca sessione corrente", "Signup chiuso di default; rate limit nel DB"], 60, 130, 600, 175),
            Node("plan", "Programma", ["GET /v1/plan → {version, plan}", "PUT /v1/plan · {expected_version, plan}", "GET /v1/plan/history", "Plan → Workout → Step; scritture concorrenti: 409"], 740, 130, 600, 175),
            Node("activities", "Attività e provenienza", ["GET /v1/activities?limit=&offset=", "POST /v1/activities/import · 1–500 ActivityRecord", "DELETE /v1/activities/{provider}/{provider_id}", "SI, timestamp con offset, source/id, client_import", "Dedup conservativa; il body non sceglie l'atleta"], 60, 405, 600, 195),
            Node("review", "Review e adattamento", ["GET /v1/review/workout → review/advice/program", "POST /v1/review/adjustments/preview", "POST /v1/review/adjustments/{proposal_id}/apply", "Apply: {expected_version, confirmed:true}", "La conferma riguarda una proposta salvata dal server"], 740, 405, 600, 195),
            Node("account", "Account, dati e capacità", ["GET /v1/me · identità account", "GET /v1/me/export · export dei propri dati", "DELETE /v1/me · {password, confirmed:true}", "GET /v1/integrations · capacità effettive", "GET /v1/openapi.json · schema autenticato"], 60, 700, 600, 195),
            Node("contract", "Isolamento del contratto", ["GET /health · readiness pubblica", "401: sessione; 403: signup/origin; 409: conflitto", "422: body invalido; 429: limite; 503: DB indisponibile", "Request DTO Pydantic; response dict Python", "DTO Swift + fixture; response_model da aggiungere"], 740, 700, 600, 195, "domain"),
            Node("locals", "API della UI personale: sistema distinto", ["/api/review/* · /api/plan/{test,sync} · /api/activities/* · /api/calendar/cleanup/*", "Chiamano Coach, usano storage personale e conferme locali; non sono /v1 e non sono un'API pubblica autenticata."], 60, 950, 1280, 90, "note"),
        ]),
        Page("05-refactoring-proposto", "Refactoring proposto: porte e adapter", "PROPOSTA, NON IMPLEMENTATA. Mantiene un backend modulare unico; separa i casi d'uso dall'ORM e dai vendor.", 1400, 1080, [
            Node("transport", "Adapter d'ingresso", ["FastAPI /v1 + DTO request/response", "Web, iOS e worker richiamano gli stessi casi d'uso"], 410, 125, 590, 105, "planned"),
            Node("usecases", "Casi d'uso applicativi", ["ImportActivities · GetWorkoutReview", "PreviewAdjustment · ApplyAdjustment", "AccountActions · contesto atleta autenticato", "Dipendono da porte, non da Session/tabelle"], 410, 325, 590, 150, "planned"),
            Node("domain", "Dominio da mantenere", ["Regole deterministiche e test già presenti", "Plan / Activity / Evidence / Adjustment", "Nessun HTTP, ORM o SDK vendor"], 60, 570, 370, 135, "domain"),
            Node("ports", "Porte da estrarre", ["PlanRepository / ActivityRepository", "ProposalRepository / AuditRepository", "UnitOfWork / Clock / SessionStore", "ActivitySource separato da WorkoutPublisher"], 540, 570, 460, 155, "planned"),
            Node("dbadapter", "Adapter di persistenza", ["SQLAlchemy → PostgreSQL / SQLite", "Query, sessioni, lock e commit qui", "Test dei casi d'uso con adapter in memoria"], 410, 840, 460, 150, "planned"),
            Node("vendoradapter", "Adapter e job vendor", ["Uno per vendor, solo dopo accesso approvato", "Token cifrati, OAuth, webhook, retry/cursori", "Import e pubblicazione sono capacità distinte"], 940, 840, 395, 150, "planned"),
            Node("priority", "Ordine suggerito", ["1. Repository + UnitOfWork", "2. DTO di risposta tipizzati", "3. Separare import/review/adattamento", "4. OAuth/job vendor e ciclo account pubblico"], 1060, 340, 275, 220, "note"),
        ], [
            Edge("transport", "usecases", "invoca", [(705, 230), (705, 325)], True),
            Edge("usecases", "domain", "regole pure", [(410, 430), (245, 430), (245, 570)], True),
            Edge("usecases", "ports", "interfacce", [(770, 475), (770, 570)], True),
            Edge("dbadapter", "ports", "implementa le porte", [(640, 840), (640, 725)], True),
            Edge("vendoradapter", "ports", "implementa capacità vendor", [(1125, 840), (1125, 770), (945, 770), (945, 725)], True),
        ]),
        Page("06-deploy-e-isolamento", "Confini operativi e dati", "Il container e lo stack privato sono predisposti nel working tree. HTTPS pubblico, dominio e hosting non sono configurati.", 1400, 990, [
            Node("device", "Dispositivo iPhone", ["UI + HealthKit + Keychain", "Dati di workout in memoria", "Upload solo dopo consenso"], 65, 130, 380, 135, "client"),
            Node("proxy", "Ingresso pubblico HTTPS", ["Reverse proxy / certificato / dominio", "Allowed hosts e proxy espliciti", "NON ancora configurato"], 555, 130, 390, 135, "planned"),
            Node("api", "Container API privato", ["app.platform.host → 2 worker", "UID 10001; root FS read-only", "127.0.0.1:8001 nello stack pilot", "Pool/timeout; niente dati personali nel build"], 555, 400, 390, 165),
            Node("secrets", "Configurazione e segreti", ["DATABASE_URL_FILE montato", "Credenziali DB fuori da Git", "Nessun token vendor ancora gestito"], 1030, 400, 305, 165, "store"),
            Node("db", "PostgreSQL condiviso", ["Archivio multi-atleta / indici / FK", "Lock atleta: scritture su stesso account serializzate", "Snapshot coerenti per le letture", "Nessuna porta host pubblicata nel pilot"], 555, 710, 390, 165, "store"),
            Node("init", "Inizializzatore separato", ["app.platform.cli init-db", "Schema 3; upgrade esplicito da 1/2", "L'avvio API verifica soltanto lo schema"], 65, 710, 380, 165),
            Node("pending", "Da completare per produzione", ["Hosting/TLS; migrazioni evolutive", "Email verification/recovery", "OAuth cifrato e job durevoli", "Backup/restore, monitoraggio e test device"], 1030, 710, 305, 165, "planned"),
        ], [
            Edge("device", "proxy", "HTTPS /v1 (futuro hosting)", [(445, 190), (555, 190)], True),
            Edge("proxy", "api", "proxy fidato", [(750, 265), (750, 400)], True),
            Edge("api", "secrets", "legge file montato", [(945, 500), (1030, 500)]),
            Edge("api", "db", "SQL/psycopg", [(750, 565), (750, 710)]),
            Edge("init", "db", "crea/verifica schema", [(445, 790), (555, 790)]),
        ]),
        Page("07-dettagli-canonici", "Dettagli della seduta: dati e layer", "Dati normalizzati e owner-bound; nessuna connessione cloud vendor approvata. HealthKit: dettagli selezionati; test device da completare.", 1400, 1060, [
            Node("source", "Fonte / adapter autorizzato", ["Garmin locale: normalizer senza rete", "Altri client: dati importati", "Unità vendor convertite prima dell'API"], 55, 140, 350, 155, "client"),
            Node("contract", "SessionDetails canonico", ["Lap, campioni e segmenti GPS", "Metri / secondi / bpm / watt", "Indici di step senza marker repeat FIT", "Dati incompleti restano espliciti"], 515, 140, 365, 175, "domain"),
            Node("api", "API dettagli per atleta e fonte", ["GET/PUT /v1/activities/{source}/{id}/details", "Bearer; versioni e hash del riepilogo", "Rifiuta tempi/distanze incoerenti"], 1000, 140, 350, 175),
            Node("plan", "Riferimento al piano storico", ["PlanVersion + workout dichiarato", "Solo versioni dello stesso atleta", "Cambio piano conserva i target passati"], 55, 455, 350, 155, "store"),
            Node("engine", "Analisi comune delle fasi", ["evaluate_measured_session", "Ordine, durata, passo e FC dei lap", "Metriche e limiti; nessuna chiamata AI"], 515, 455, 365, 155, "domain"),
            Node("db", "Storage separato", ["ac_activities: riepiloghi leggeri", "ac_activity_details: dati per fonte", "FK owner/fonte/ID; cascade delete", "Hash cambiato: dettagli obsoleti"], 1000, 455, 350, 175, "store"),
            Node("local", "Review personale Garmin", ["Parser Garmin + analisi comune", "Target dal piano locale corrente", "Originale remoto non verificato"], 55, 805, 350, 155, "client"),
            Node("ios", "Review nativa SwiftUI", ["Fasi, lap e dinamiche", "Grafici FC/passo in unità separate", "MapKit: segmenti GPS distinti"], 515, 805, 365, 155, "client"),
            Node("gates", "Integrazioni da completare", ["Accessi vendor approvati", "HealthKit: test device/permessi", "AI remoto e release firmata"], 1000, 805, 350, 155, "planned"),
        ], [
            Edge("source", "contract", "normalizza", [(405, 215), (515, 215)]),
            Edge("contract", "api", "JSON", [(880, 215), (1000, 215)]),
            Edge("api", "db", "scrittura versionata", [(1175, 315), (1175, 455)]),
            Edge("db", "engine", "lettura coerente", [(1000, 530), (880, 530)]),
            Edge("plan", "engine", "target della versione riferita", [(405, 530), (515, 530)]),
            Edge("engine", "ios", "detailed_review JSON", [(697, 610), (697, 805)]),
            Edge("local", "engine", "stesso calcolo", [(230, 805), (230, 700), (515, 700), (515, 610)]),
        ]),
        Page("08-redis-proposto", "Redis e job: proposta per il servizio scalabile", "Architettura futura: Redis, dispatcher e worker vendor non sono implementati. PostgreSQL resta la fonte autorevole.", 1400, 1070, [
            Node("api", "API della piattaforma", ["Richieste utenti e webhook futuri", "Autenticazione e owner dell'atleta", "Accoda lavori; risponde rapidamente"], 55, 140, 350, 155),
            Node("postgres", "PostgreSQL", ["Piani, attività e audit già presenti", "Job/outbox: da implementare", "Stato e idempotenza persistenti"], 520, 140, 365, 155, "store"),
            Node("redis", "Redis: broker e cache", ["Coda worker; nessun token in chiaro", "Cache review con owner/hash e TTL", "Persistenza/eviction da configurare"], 1000, 140, 350, 155, "planned"),
            Node("dispatcher", "Dispatcher dell'outbox", ["Pubblica job committati nel DB", "Recupera consegne interrotte", "Invia ID, non dati sanitari"], 520, 455, 365, 155, "planned"),
            Node("worker", "Worker separati", ["Refresh e backfill", "Retry/backoff e quote per vendor", "Idempotenza; stato aggiornato in SQL"], 55, 805, 350, 155, "planned"),
            Node("vendors", "API vendor approvate", ["Garmin / COROS / Suunto / altri", "Token per atleta gestiti dal server", "Adapter → ActivityRecord/SessionDetails"], 520, 805, 365, 155, "planned"),
            Node("results", "Review e stato del lavoro", ["Dati definitivi nel database", "Notifiche e aggiornamenti del client", "Cache ricostruibile dopo perdita Redis"], 1000, 805, 350, 155, "planned"),
        ], [
            Edge("api", "postgres", "dati + job in transazione", [(405, 215), (520, 215)], True),
            Edge("postgres", "dispatcher", "job pending", [(700, 295), (700, 455)], True),
            Edge("dispatcher", "redis", "pubblica ID job", [(885, 530), (1175, 530), (1175, 295)], True),
            Edge("redis", "worker", "consegna ai worker", [(1000, 215), (945, 215), (945, 705), (230, 705), (230, 805)], True),
            Edge("worker", "vendors", "OAuth server + adapter", [(405, 880), (520, 880)], True),
            Edge("vendors", "worker", "dati restituiti", [(700, 960), (700, 1005), (230, 1005), (230, 960)], True),
            Edge("worker", "postgres", "salva dati e stato", [(55, 880), (25, 880), (25, 355), (700, 355), (700, 295)], True),
            Edge("postgres", "results", "legge risultati", [(800, 295), (800, 335), (1375, 335), (1375, 755), (1175, 755), (1175, 805)], True),
        ]),
    ]


def route_catalog():
    paths = ["app/platform/main.py", "app/main.py", *[str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "app/api").glob("*.py")]]
    rows = []
    for path in paths:
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        prefix = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "APIRouter":
                prefix = next((ast.literal_eval(k.value) for k in node.keywords if k.arg == "prefix"), "")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for deco in node.decorator_list:
                    if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute) and deco.func.attr in {"get", "post", "put", "delete", "patch"}:
                        rows.append({"system": "platform" if path.startswith("app/platform") else "personal", "method": deco.func.attr.upper(), "path": prefix + ast.literal_eval(deco.args[0]), "handler": node.name, "file": path, "line": node.lineno})
    return sorted(rows, key=lambda r: (r["system"], r["path"], r["method"]))


def drawio_page(parent, page):
    diagram = ET.SubElement(parent, "diagram", id=page.slug, name=page.title)
    model = ET.SubElement(diagram, "mxGraphModel", dx=str(page.width), dy=str(page.height), grid="1", gridSize="10", guides="1", tooltips="1", connect="1", arrows="1", fold="1", page="1", pageScale="1", pageWidth=str(page.width), pageHeight=str(page.height))
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")
    title = ET.SubElement(root, "mxCell", id="title", value=html.escape(page.title) + "<br><font size='3'>" + html.escape(page.subtitle) + "</font>", style="text;html=1;align=left;verticalAlign=middle;fontSize=24;fontStyle=0;whiteSpace=wrap;", vertex="1", parent="1")
    ET.SubElement(title, "mxGeometry", x="60", y="20", width=str(page.width - 120), height="70", **{"as": "geometry"})
    for node in page.nodes:
        fill, stroke = COLORS[node.kind]
        label = f"<b>{html.escape(node.title)}</b><br>" + "<br>".join(html.escape(s) for s in node.lines)
        cell = ET.SubElement(root, "mxCell", id=node.id, value=label, style=f"rounded=1;whiteSpace=wrap;html=1;align=left;verticalAlign=middle;spacing=15;fontSize=15;fillColor={fill};strokeColor={stroke};fontColor=#17212f;dashed={int(node.kind == 'planned')};", vertex="1", parent="1")
        ET.SubElement(cell, "mxGeometry", x=str(node.x), y=str(node.y), width=str(node.w), height=str(node.h), **{"as": "geometry"})
    for index, edge in enumerate(page.edges):
        cell = ET.SubElement(root, "mxCell", id=f"edge-{index}", value=edge.label, style=f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;fontSize=13;strokeColor=#526071;strokeWidth=1.5;labelBackgroundColor=#ffffff;dashed={int(edge.planned)};", edge="1", parent="1", source=edge.source, target=edge.target)
        geometry = ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
        if len(edge.points) > 2:
            array = ET.SubElement(geometry, "Array", **{"as": "points"})
            for x, y in edge.points[1:-1]:
                ET.SubElement(array, "mxPoint", x=str(x), y=str(y))


def svg_page(page):
    svg = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", width=str(page.width), height=str(page.height), viewBox=f"0 0 {page.width} {page.height}", role="img", **{"aria-label": page.title})
    ET.SubElement(svg, "title").text = page.title
    ET.SubElement(svg, "desc").text = page.subtitle
    ET.SubElement(svg, "rect", width="100%", height="100%", fill="#ffffff")
    defs = ET.SubElement(svg, "defs")
    marker = ET.SubElement(defs, "marker", id="arrow", viewBox="0 0 10 10", refX="9", refY="5", markerWidth="7", markerHeight="7", orient="auto-start-reverse")
    ET.SubElement(marker, "path", d="M 0 0 L 10 5 L 0 10 z", fill="#526071")
    def text(x, y, value, size=16, weight="400", fill="#17212f"):
        item = ET.SubElement(svg, "text", x=str(x), y=str(y), fill=fill, **{"font-family": "Segoe UI, Arial, sans-serif", "font-size": str(size), "font-weight": weight})
        item.text = value
    text(60, 47, page.title, 27, "500")
    for i, line in enumerate(textwrap.wrap(page.subtitle, width=int((page.width - 120) / 7.8))):
        text(60, 76 + i * 19, line, 15, fill="#536173")
    for edge in page.edges:
        if not edge.points:
            continue
        ET.SubElement(svg, "polyline", points=" ".join(f"{x},{y}" for x, y in edge.points), fill="none", stroke="#526071", **{"stroke-width": "1.7", "stroke-dasharray": "7 5" if edge.planned else "none", "marker-end": "url(#arrow)"})
    for node in page.nodes:
        fill, stroke = COLORS[node.kind]
        ET.SubElement(svg, "rect", x=str(node.x), y=str(node.y), width=str(node.w), height=str(node.h), rx="10", fill=fill, stroke=stroke, **{"stroke-width": "1.2", "stroke-dasharray": "7 5" if node.kind == "planned" else "none"})
        lines = [(s, 18, "500") for s in textwrap.wrap(node.title, width=int((node.w - 32) / 9.5))]
        for line in node.lines:
            lines.extend((s, 15, "400") for s in textwrap.wrap(line, width=int((node.w - 32) / 7.8)))
        used = sum(24 if size == 18 else 21 for _, size, _ in lines)
        assert used <= node.h - 16, f"Text exceeds node: {page.slug}/{node.id}: {used}/{node.h}"
        baseline = node.y + max(23, (node.h - used) // 2 + 17)
        for value, size, weight in lines:
            text(node.x + 16, baseline, value, size, weight)
            baseline += 24 if size == 18 else 21
    # Label the longest free segment; omit cramped labels in SVG, retained in editable XML.
    for edge in page.edges:
        segments = list(zip(edge.points, edge.points[1:], strict=False))
        if not edge.label or not segments:
            continue
        (x1, y1), (x2, y2) = max(segments, key=lambda pair: abs(pair[1][0] - pair[0][0]) + abs(pair[1][1] - pair[0][1]))
        available = abs(x2 - x1) if y1 == y2 else 250
        if y1 == y2 and available < len(edge.label) * 7 + 20:
            continue
        x, y = ((x1 + x2) / 2 - len(edge.label) * 3.4, y1 - 9) if y1 == y2 else (x1 + 10, (y1 + y2) / 2)
        if x + len(edge.label) * 7.4 > page.width - 20:
            x = x1 - len(edge.label) * 7.4 - 10
        text(x, y, edge.label, 14, fill="#435168")
    return svg


def generate():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    document = ET.Element("mxfile", host="app.diagrams.net", agent="EnduranceCoach architecture generator", version="24.7.17", type="device", compressed="false")
    for page in pages():
        ids = {node.id for node in page.nodes}
        assert len(ids) == len(page.nodes)
        assert all(edge.source in ids and edge.target in ids for edge in page.edges)
        assert all(n.x >= 0 and n.y >= 0 and n.x + n.w <= page.width and n.y + n.h <= page.height for n in page.nodes)
        drawio_page(document, page)
        tree = ET.ElementTree(svg_page(page))
        ET.indent(tree)
        tree.write(OUTPUT / f"{page.slug}.svg", encoding="utf-8", xml_declaration=True)
    tree = ET.ElementTree(document)
    ET.indent(tree)
    tree.write(OUTPUT / "endurance-coach.drawio", encoding="utf-8", xml_declaration=True)
    (OUTPUT / "api-catalog.json").write_text(json.dumps(route_catalog(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Created {len(pages())} architecture views, editable XML and a source-derived API catalog in {OUTPUT}")


if __name__ == "__main__":
    generate()
