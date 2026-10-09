# Contesto comune del coach

`app/coaching_context.py` prepara le evidenze del coach senza rete, accesso vendor o credenziali. La conversazione personale e il backend autenticato usano lo stesso formato. Questo passaggio prepara il collegamento AI richiesto; non esegue inferenze né attiva un account ChatGPT.

## API autenticata

`GET /v1/coach/context` richiede la sessione dell'atleta e il questionario salvato. Restituisce `context`, `context_hash`, `ai_status=not_connected` e `inference_performed=false`. Il server deriva il proprietario dalla sessione, non da un parametro o dal body. La risposta non viene memorizzata nella cache HTTP. Un atleta senza piano o dispositivo riceve comunque il proprio profilo e l'eventuale storico dichiarato.

Profilo, piano, attività e dettagli vengono letti nella stessa snapshot del database. La richiesta non apre sessioni Garmin, non chiama OpenAI e non modifica programmi o proposte.

## Copertura e selezione

- Profilo dichiarato e versione; programma corrente senza il dizionario legacy `Plan.athlete`.
- Finestra del piano da 14 giorni prima a 14 giorni dopo la data corrente, con numero di workout incluso e totale.
- Ultime 20 attività concluse entro gli ultimi 42 giorni. Un'attività che non è ancora finita viene esclusa. La copertura segnala quando lo storico disponibile supera 20 attività.
- Evidenze delle ultime due sedute: fasi, target, split, FC, passo, dinamiche, giudizi e azioni, quando disponibili e aggiornati.
- Massimo 100 fasi, 100 lap e 120 campioni per seduta; selezione rappresentativa dell'intervallo, conservando primo e ultimo elemento. I conteggi disponibili/inclusi e la riduzione sono espliciti. Il giudizio deterministico usa l'analisi originale; l'AI non deve interpretare il campione come prova di tutti gli step.
- Dettagli obsoleti o non verificati riportano lo stato, senza riutilizzare un'analisi precedente come evidenza valida.
- Campi GPS/percorso, credenziali, dati di autenticazione e metadati liberi del vecchio profilo sono esclusi. Le risposte testuali volontarie al questionario restano nel contesto: possono contenere informazioni che l'atleta ha scelto di dichiarare.

Il limite complessivo è 300.000 byte JSON. Un contesto più grande viene rifiutato, senza tagli silenziosi. Il backend rifiuta anche una copertura che supera 2.000 attività nel periodo considerato. L'impronta cambia con le evidenze selezionate o le loro versioni; l'orario esatto della lettura non causa da solo un cambiamento. La data corrente rimane parte del contesto.

## Trasporto AI e pubblicazione

Il prodotto richiesto è **gratuito e open source**, con licenza MIT del codice e attribuzioni dei componenti terzi conservate. Il collegamento deve usare il piano ChatGPT dell'atleta e un consenso separato; non è previsto un ripiego su chiave API. Il percorso ufficiale open source è documentato da [OpenAI](https://developers.openai.com/siwc/quickstart). L'idoneità di un account, il corretto callback nativo e una vera inferenza devono ancora essere verificati prima di presentare il collegamento iOS come attivo.

`context_hash` prepara il controllo di contesto al ritorno da una richiesta AI. Una risposta o una bozza AI non può aggirare i controlli di adattamento, l'anteprima e la conferma dell'atleta.

Le prove coprono isolamento tra atleti, autenticazione, funzionamento senza piano, assenza di campi GPS e marker segreti legacy, dettaglio di FC/stride conservato, campioni ridotti con copertura esplicita, attività non concluse, impronte/versioni e invalidazione dei dettagli dopo modifica della fonte.
