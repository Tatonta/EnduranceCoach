# Dettagli Apple Health: lettura selezionata, anteprima e invio

Il client iOS può ora leggere i dettagli della singola seduta scelta nell'anteprima Apple Health. L'importazione dei riepiloghi degli ultimi 42 giorni resta separata. La lettura dei dettagli richiede soltanto i tipi HealthKit necessari per corsa/bici e, se richiesto dall'atleta, il percorso già registrato. Non vengono richiesti permessi di scrittura né la posizione attuale.

## Flusso dell'atleta

1. In Account, leggi i workout e controlla l'anteprima dei riepiloghi.
2. Seleziona una corsa o un'uscita bici e premi **Leggi lap, campioni e dinamiche**. Il percorso GPS è una scelta di lettura facoltativa, disattivata per default.
3. Controlla conteggi, copertura e dinamiche nell'anteprima dei dettagli. Scegli se includere i dettagli nell'importazione e, separatamente, se includere il GPS.
4. Conferma l'invio nella schermata precedente. Preparare l'anteprima non invia dati al backend.

La lettura riuscita della finestra di autorizzazione non dimostra che ogni tipo di dato sia leggibile. Una risposta vuota può dipendere da dati mancanti, permessi limitati o dall'app del produttore che non esporta quelle misure. Non si sostituiscono dati del resto della giornata ai campioni del workout.

## Tipi e normalizzazione

La corsa usa FC, velocità, stride length, ground contact time, oscillazione verticale, potenza, passi e distanza, dove disponibili. La bici usa FC, velocità, potenza, cadenza e distanza. Le query usano il predicato del workout associato; le misure fuori dall'intervallo della seduta vengono scartate. Metri, secondi, m/s e watt vengono mantenuti nel contratto canonico.

`HealthEvidenceBuilder` è una normalizzazione Swift senza rete/HealthKit. Combina valori soltanto nelle rispettive finestre temporali, senza interpolare HR o altre misure assenti. La cadenza di corsa, quando leggibile, è derivata dal numero di passi nella finestra misurata e viene omessa nelle finestre che includono pause. La cadenza della pedalata rimane una quantità distinta.

I lap vengono costruiti da eventi lap o segmenti già registrati. Non si inventano warmup, recuperi o collegamenti a un programma. Le pause esplicite vengono considerate; se il tempo attivo non coincide con quello del workout, i lap vengono omessi. La distanza di un lap rimane sconosciuta quando manca una copertura completa o una misura attraversa una pausa in modo ambiguo. Le medie HR dei lap usano i campioni interamente contenuti nelle finestre attive disponibili.

La geometria conserva segmenti diversi e spezza i tratti con punti invalidi, buchi temporali o precisione insufficiente. I dati vengono ridotti ai limiti del backend senza colmare i buchi. I limiti attuali sono 20.000 letture per metrica, 50.000 punti GPS complessivi e dieci sedute dettagliate selezionate per importazione. Superare una lettura massima interrompe quella lettura, lasciando disponibile l'importazione dei riepiloghi; non viene presentata una scansione troncata come completa.

## Coerenza fra importazioni

Il backend restituisce `source_activity_hashes` nella risposta di `/v1/activities/import`, nello stesso momento transazionale in cui salva i riepiloghi. Il client acquisisce versione/hash dei dettagli e verifica che il riepilogo sia ancora quello della propria importazione, poi invia `HealthDetailWrite` con il relativo hash. Un cambiamento concorrente impedisce l'associazione dei dettagli al riepilogo sbagliato.

Riepiloghi e dettagli sono richieste distinte. Un errore dopo il salvataggio dei riepiloghi lascia l'anteprima disponibile; non viene dichiarato completo l'invio dei dettagli. Non ci sono retry automatici delle mutazioni. Ripetere l'importazione dello stesso ID fonte aggiorna il record esistente, mentre le versioni dei dettagli proteggono le scritture concorrenti.

Le anteprime rimangono in memoria e vengono eliminate con annullamento/logout. I dati inviati appartengono all'account autenticato sul servizio configurato. Il percorso non viene inviato a ChatGPT dal flusso locale di coaching.

## Evidenze e limiti

I test nativi verificano unità e nomi delle chiavi JSON, dati HR assenti, lap con tempi attivi non verificabili, distanza parziale, buchi GPS e riduzione ai limiti. Le verifiche API confrontano l'hash restituito dall'importazione con quello della fonte. Build/test SDK non dimostrano ancora la lettura sul telefono dell'atleta, l'esito dei permessi o i dati esportati da ciascun modello di watch; questi controlli richiedono un dispositivo e l'autorizzazione dell'utente.

Fonti primarie consultate:

- [HealthKit quantity identifiers](https://developer.apple.com/documentation/healthkit/hkquantitytypeidentifier)
- [Workout events](https://developer.apple.com/documentation/healthkit/hkworkouteventtype)
- [Workout route query](https://developer.apple.com/documentation/healthkit/hkworkoutroutequery)
