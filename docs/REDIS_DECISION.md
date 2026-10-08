# Redis per EnduranceCoach: proposta e momento d'introduzione

Decisione proposta l'8 ottobre 2026: introdurre Redis insieme ai worker del primo flusso vendor approvato. Il pilot corrente usa PostgreSQL per transazioni, isolamento, sessioni e rate limit; non richiede Redis per mantenere quei vincoli. Redis non è stato installato o aggiunto al deploy.

| Responsabilità | Collocazione proposta |
| --- | --- |
| Piani, profili, attività, dettagli, credenziali protette, conferme e audit | PostgreSQL / gestione dei segreti appropriata |
| Stato definitivo e idempotenza dei job | PostgreSQL |
| Trasporto dei job verso worker separati | Redis come broker, con libreria di job da scegliere/testare |
| Review calcolate e letture ripetute | Cache Redis opzionale, owner/hash/versione e TTL; ricostruibile dal DB |
| Quote per connessione/vendor | Controllo nei worker; rate limit distribuito se necessario |

Per il flusso di sincronizzazione si propone una outbox transazionale: l'API salva il lavoro pending con la transazione dei dati, un dispatcher pubblica l'ID del job e il worker registra l'esito. Un'interruzione del broker deve lasciare il lavoro recuperabile nel database; la riconsegna deve essere tollerata attraverso idempotenza. Cache e broker hanno esigenze diverse di persistenza/eviction e vanno configurati di conseguenza. Le modifiche al piano continuano a usare versioni, lock e transazioni PostgreSQL, mantenendo la conferma dell'atleta.

Redis è un'opzione concreta per il broker perché è supportato da [Celery](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html). La scelta di Celery o di un altro worker non è ancora stata implementata. Occorre verificare retry, quote, lavori interrotti e assenza di duplicazioni nel caso reale dei vendor.

Le garanzie del broker dipendono dalla configurazione: Redis offre snapshot RDB, log AOF e diverse politiche di scrittura su disco. RDB può perdere le modifiche successive allo snapshot; AOF ogni secondo conserva un compromesso fra prestazioni e durata dei dati. Per questo la proposta mantiene lo stato recuperabile dei job nel database. [Documentazione della persistenza Redis](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/).

Lo schema visuale è nella pagina **Redis e job proposti** di [endurance-coach.drawio](architecture/endurance-coach.drawio). I collegamenti tratteggiati descrivono lavoro futuro, non servizi già attivi.
