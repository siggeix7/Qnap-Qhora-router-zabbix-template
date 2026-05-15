# Sources

Questa directory contiene la documentazione e gli strumenti usati per:

1. Scoprire le REST API non documentate del QNAP QuRouter
2. Provarle in modo sicuro (solo `GET`, eccetto il login)
3. Progettare il template Zabbix 7.0

Tutti i file qui presenti sono stati sanificati e non contengono credenziali, IP reali, MAC address, serial number o altri dati sensibili.

## Struttura

| File / Directory | Descrizione |
| --- | --- |
| `README.md` | Panoramica del metodo di reverse engineering |
| `api-discovery.md` | Come sono stati scoperti gli endpoint API dal frontend QuRouter |
| `zabbix-template-design.md` | Come e perche e stato progettato il template Zabbix |
| `tools/` | Versioni sanificate degli script di discovery e probe |

## Come Sono State Scoperte Le API

Il QuRouter non ha documentazione API pubblica. Il frontend web pero le usa tutte. Il metodo e stato:

1. Scaricare gli asset statici del frontend (HTML, JS, CSS) dal router
2. Analizzare i bundle JavaScript minificati per trovare riferimenti agli endpoint `/miro/api/v1/` e `/miro/api/v2/`
3. Ricostruire la mappa endpoint -> funzione frontend
4. Provare ogni endpoint `GET` con autenticazione Bearer token
5. Analizzare le risposte per schema e campi utili al monitoraggio

Vedi `api-discovery.md` per i dettagli tecnici.

## Come E Stato Progettato Il Template Zabbix

Il template usa un approccio "master + dependent items":

1. Un item master `SCRIPT` fa login e raccoglie tutte le risposte API in un unico JSON
2. I dependent item estraggono i singoli valori tramite preprocessing JSONPath
3. Le low-level discovery (LLD) rule scoprono dinamicamente WAN, porte Ethernet, switch e bande Wi-Fi
4. I trigger prototypes generano allarmi per ogni entita scoperta

Vedi `zabbix-template-design.md` per le decisioni di design.

## Strumenti

Gli script in `tools/` sono versioni sanificate di quelli usati durante il reverse engineering. Per usarli:

```bash
# 1. Crea un file credenziali (non committarlo mai)
echo "username=tuo_user
password=tua_password
base_url=https://<ROUTER_IP>" > credentials.txt

# 2. Scopri gli endpoint API
python3 sources/tools/discover_qnap_api.py --base-url https://<ROUTER_IP>

# 3. Prova gli endpoint con autenticazione
python3 sources/tools/authenticated_probe_qnap.py --base-url https://<ROUTER_IP> --credentials credentials.txt --zabbix-candidates
```

## Note Di Sicurezza

- Questi endpoint API **non sono documentati ufficialmente da QNAP** e potrebbero cambiare con aggiornamenti firmware
- Usare solo `GET` per il monitoraggio. Qualsiasi `POST`/`PUT`/`DELETE` puo modificare la configurazione del router
- Il login con `force=true` chiude le sessioni web eventualmente gia aperte
- Non committare mai file con credenziali, token o cookie
- I file JSON generati dai probe contengono dati sensibili della tua rete: non pubblicarli
