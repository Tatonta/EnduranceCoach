# Review dettagliata e account ChatGPT

La pagina locale `/review` legge adesso i dettagli reali Garmin: riepilogo completo, lap, split tipizzati, campioni e tempo nelle zone FC. Il motore di analisi separa riscaldamento, lavoro, recuperi e defaticamento usando `intensityType` e `wktStepIndex`; raggruppa gli autolap consecutivi dello stesso step e conserva le ripetute come fasi distinte. La fase repeat FIT viene dopo i suoi figli: non è un lap di lavoro.

La pagina presenta giudizi positivi/scostamenti, azioni pratiche, confronto dei target di ritmo/durata, FC e zone Garmin, dinamiche di corsa, lap, grafico passo/FC e mappa del percorso. Stride length è convertita da cm a metri e mostrata con due decimali. La cadenza usa il valore completo Garmin; i valori `directRunCadence` per singola gamba non vengono scambiati per passi/min complessivi. Corsa/cammino/soste provengono dai soli split `RWD_*`, evitando il doppio conteggio degli split di fase.

Le soglie temporali/ritmo dell'analisi locale sono euristiche. La Z2 è un riferimento indicativo solo per sedute dichiarate facili, se il piano non specifica un target HR. Le zone sono quelle configurate in Garmin: non sono una diagnosi o una stima automatica della soglia fisiologica. Le differenze FC fra lavoro e recupero riguardano medie di fase, non un test clinico di recupero cardiaco. Il confronto usa il piano corrente; la versione originale del workout caricato non è verificata. Meteo, RPE, dolore e sonno richiedono contesto dell'atleta.

## Il cervello della review: ChatGPT dell'utente

Il bottone **Continue with ChatGPT** avvia il flusso ufficiale **Sign in with ChatGPT / ChatGPT plan usage**, con PKCE, state, nonce e callback loopback `http://127.0.0.1:<porta>/auth/callback`. Non serve una chiave API OpenAI. L'utente autorizza l'identità e, separatamente, l'utilizzo del suo piano ChatGPT; una sola identità verificata non abilita inferenza.

Prima registrazione: `dynamic_agent_client`, host UUID persistente e `agent_name_hint=EnduranceCoach`. Il client ID emesso viene usato per lo scambio del codice e riutilizzato per registrazioni successive; non si usa `dynamic_agent_client` nel token exchange. Firma RS256, issuer, audience, scadenza e nonce dell'ID token sono verificati tramite JWKS OpenAI. Le credenziali non sono esposte al JavaScript della pagina. Su Windows il vault è cifrato con DPAPI dell'utente; su Unix il percorso è owner-only con file `0600`. Il codice di callback è rimosso dai log di accesso.

La pagina distingue account/workspace salvati, consenso al piano, modello disponibile, primo messaggio di utilizzo del piano e **Gestisci utilizzo**. Il catalogo modelli arriva dall'account collegato; non si presume un modello disponibile. La review invia metriche, fasi e storico necessario, senza percorso GPS, credenziali o identificativi del profilo Garmin. Il contesto del profilo atleta configurato nel piano può essere incluso dove rilevante per il coaching. Non c'è accesso alle conversazioni o memorie ChatGPT: lo storico analizzato viene dall'app.

Inferenza: OAuth Bearer sul pubblico endpoint Responses, `store=false`, `stream=true`, contesto in `input`, istruzioni separate. Campi non supportati dal percorso plan-usage vengono omessi. Il risultato è accettato solo dopo `response.completed`; interruzioni, risultati incompleti e limiti di utilizzo non vengono trasformati in review riuscite. Il servizio non passa silenziosamente a una chiave API o ad altra fatturazione. La risposta viene mantenuta localmente per attività, account e hash del contesto; cambiamenti di dati/account durante l'inferenza invalidano il risultato.

ChatGPT valuta seduta e storico e formula il commento. Il software prepara i dati misurati e conserva i vincoli sulle azioni: il modello non scrive direttamente un programma né sincronizza un workout. Le proposte di adattamento continuano a richiedere evidenze e conferma esplicita.

## Disponibilità e verifica

Il percorso implementato è per la **versione personale locale**, con account ChatGPT idonei. Le fonti OpenAI documentano disponibilità per progetti open source/locali e client privati selezionati; per app a pagamento o ospitate remotamente bisogna richiedere accesso. Non è un'abilitazione già ottenuta per App Store o piattaforma pubblica.

Il collegamento reale e la prima inferenza devono essere completati dall'utente nel browser con il proprio account. Fino a quel momento la UI mostra che l'account è da collegare; non presenta una risposta locale come se fosse ChatGPT. I test automatici usano identità/tokens sintetici e coprono PKCE/host stabile, state e riuso del callback, signature/audience/nonce/expiry, consenso mancante, stream completato/interrotto, dati segreti non esposti e revoca locale.

Fonti ufficiali verificate l'8 ottobre 2026:

- [Quickstart e disponibilità](https://developers.openai.com/siwc/quickstart)
- [Registrazione locale e sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Account, protezione e refresh](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
- [Modelli e inferenza](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Limiti della preview](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)

## Codice e API locali

- `session_analysis.py`: normalizzazione e analisi misurata, senza rete/DB.
- `workout_details.py`: lettura Garmin esplicita, cache privata e preparazione del contesto.
- `chatgpt.py`: vault, OAuth ufficiale, catalogo, refresh, revoca e inferenza.
- `session_review.py`: `GET /api/session-review`, `POST /api/session-review/refresh`, `POST /api/session-review/brain`; endpoint locali `/api/chatgpt/{status,connect,models,select,welcome,disconnect}` e callback `/auth/callback`.
- `session-review.js`: dati, chart, mappa, selezione seduta e collegamento account; testi del modello resi come testo, non HTML eseguibile.

Questo percorso non aggiunge un token ChatGPT globale al backend multi-atleta `/v1`, né condivide una sessione personale fra utenti della piattaforma.
