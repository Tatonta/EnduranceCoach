# Coaching anche senza orologio

La home Coach permette di registrare una seduta conclusa senza account del produttore o permessi Apple Health. Il modulo raccoglie nome, sport, inizio con fuso orario, durata, distanza facoltativa, sforzo percepito 1–10 facoltativo, sensazioni, eventuali fastidi, completamento dichiarato e note.

Sono **dati dichiarati**, non misure del dispositivo. Una distanza omessa resta non indicata: non viene presentata come zero chilometri e non genera un passo. Quando distanza e durata sono indicate, l'eventuale passo è il rapporto tra quei valori dichiarati; non dimostra il ritmo degli intervalli. FC, dislivello, training effect, GPS e running dynamics non vengono inventati. Il registro rifiuta sedute non ancora concluse.

## Dal feedback al coach

La seduta compare nello storico e nel contesto inviato dopo una domanda esplicita a ChatGPT. La review distingue aspetti dichiarati riusciti, scostamenti dal previsto, stanchezza e note; non tenta chiamate Garmin per queste sedute. La UI non mostra una mappa, lap o dinamiche inesistenti. Passare a un'attività Garmin ripristina la vista misurata e le relative limitazioni.

Il motore di adattamento esclude le sedute manuali dal confronto prestazionale. Quattro tempi dichiarati apparentemente in miglioramento non abilitano il popup; feedback e RPE non diventano prove di una soglia fisiologica o di un miglioramento misurato. Una segnalazione di fastidio resta una dichiarazione, senza inferirne la causa.

Il modulo va usato per attività non già importate. Il backend non unisce automaticamente una seduta manuale a una del dispositivo: una coincidenza di tempo/distanza non dimostra che siano la stessa seduta. L'eventuale risoluzione assistita dei duplicati resta un'evoluzione futura.

## Contratto comune e persistenza

`app/session_feedback.py` definisce `ManualSession`, `SessionFeedback` e la lettura dei feedback. Il servizio converte una dichiarazione in `ActivityRecord` con `source=manual`, `evidence_kind=self_reported`, `distance_known` e feedback tipizzato. Nessuna credenziale vendor è necessaria.

| API | Comportamento |
| --- | --- |
| `POST /api/activities/manual` | Dashboard locale; richiede questionario salvato |
| `DELETE /api/activities/manual/{request_id}` | Solo record manuali dell'utente locale; non può cancellare record Garmin |
| `POST /v1/activities/manual` | Account autenticato e profilo; crea/aggiorna il proprio record manuale |
| `DELETE /v1/activities/manual/{request_id}` | Route di cancellazione delle attività esistente, con fonte manual e controllo del proprietario |

`request_id` è un UUID v4 generato dal client e mantenuto durante i tentativi di salvataggio dello stesso modulo. Ripetere la richiesta aggiorna il medesimo record, senza creare una seconda seduta. Non ci sono retry automatici delle mutazioni. Chiudere e aprire un nuovo modulo crea una nuova identità: il software non deduce che due dichiarazioni siano identiche.

Il body non accetta atleta, fonte o metriche dell'orologio scelti dal client. Il controllo di account è quello delle attività; lo storico, export e cancellazione account includono anche le dichiarazioni. I dati sono conservati nei record JSON esistenti: non è richiesta una revisione del database successiva alla 2. Non vengono scritti nelle fixture o nel repository.

## Web e iPhone

Nel web il bottone **Registra una seduta** è nella home Coach. La review presenta il feedback dichiarato e nasconde mappa, split e dinamiche per quella fonte. La registrazione funziona prima della creazione del programma; senza programma lo storico rimane consultabile nella home e utilizzabile nella conversazione.

Nel client SwiftUI il modulo è nella scheda Coach e invia il feedback al servizio configurato, senza aprire HealthKit. Le ultime cinque dichiarazioni tra le cinquanta attività recenti compaiono nella home. La review conserva la distinzione tra distanza sconosciuta, passo dichiarato e metriche misurate. Il collegamento AI remoto/iOS è ancora da abilitare; la conversazione ChatGPT resta disponibile nella versione personale locale.

Le verifiche coprono campi e fusi orari, fine della seduta, idempotenza, mancata invenzione di metriche, isolamento tra account, export e cancellazione, esclusione dal trend e review senza chiamate vendor. La prova nel browser usa un server separato, dati sintetici e campioni Garmin sintetici già in cache. I test Swift verificano il contratto del feedback e i parametri di query delle attività; non sostituiscono la verifica su dispositivo reale.
