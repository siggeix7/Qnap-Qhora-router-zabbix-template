# API Discovery

Come sono state scoperte le REST API del QNAP QuRouter.

## Premessa

QNAP non fornisce documentazione pubblica per le API del QuRouter. Il frontend web pero e un client di queste API: ogni azione nell'interfaccia corrisponde a una chiamata HTTP.

## Metodo

### Fase 1 - Download Degli Asset Frontend

Il primo passo e scaricare gli stessi file che il browser carica quando si apre l'interfaccia web del router:

```
GET https://<ROUTER_IP>/           -> index.html
GET https://<ROUTER_IP>/js/...     -> bundle JavaScript
GET https://<ROUTER_IP>/css/...    -> fogli di stile
```

L'`index.html` riferisce i bundle JS e CSS tramite tag `<script>` e `<link>`.

### Fase 2 - Analisi Dei Bundle JavaScript

I bundle JS contengono la logica del frontend, incluso il modo in cui vengono costruiti gli URL delle API. Cercando pattern come:

- `/miro/api/v1/`
- `/miro/api/v2/`
- Template URL come `` `/miro/api/v2/network/ports/${id}` ``

Si possono estrarre:
- Path degli endpoint
- Chiavi/nomi usati dal frontend per referenziarli
- Il file JS in cui ogni endpoint e definito
- Se il path contiene parametri dinamici

### Fase 3 - Ricostruzione Della Mappa Endpoint

Ogni endpoint viene catalogato con:

| Campo | Esempio |
| --- | --- |
| version | `v1`, `v2` |
| key | `PortsStatus`, `NetworkStatus`, `Clients` |
| path | `/miro/api/v2/network/ports_status` |
| source | nome del file JS |
| dynamic | `true` se il path contiene variabili |

### Fase 4 - Estrazione Delle Operazioni

Oltre ai path, i bundle JS contengono le chiamate effettive: chi fa cosa, con quale metodo HTTP e con quale payload. Cercando pattern come:

```js
await api.post("/miro/api/v1/login", { username, password })
await api.get(`/miro/api/v2/network/ports/${id}`)
```

Si ricostruisce per ogni operazione:
- Metodo HTTP (`GET`, `POST`, `PUT`, `DELETE`)
- Endpoint di riferimento
- Se e una chiamata sicura per il monitoraggio (solo `GET`)

### Fase 5 - Probe Autenticato

Una volta mappati gli endpoint `GET` sicuri, si provano con autenticazione:

1. Login su `/miro/api/v1/login` con `POST`
2. Si ottiene un `access_token`
3. Si usa `Authorization: Bearer <token>` su ogni `GET`
4. Si analizza la risposta: status code, schema JSON, campi utili

## Login

Il login locale usa lo stesso meccanismo del frontend web:

```
POST /miro/api/v1/login
Content-Type: application/json

{
  "username": "<user>",
  "password": "<base64-utf8>",
  "force": true,
  "remember_me": false,
  "qid_login": false
}
```

Note importanti:
- La password va codificata in **base64 UTF-8** prima dell'invio
- `force: true` e necessario se esiste gia una sessione attiva (altrimenti il router rifiuta)
- La risposta contiene `result.access_token` da usare come Bearer token
- Il login forzato puo chiudere sessioni web gia aperte

## Struttura Delle Risposte

Quasi tutte le risposte seguono questo schema:

```json
{
  "error_code": 0,
  "error_message": "",
  "result": { ... }
}
```

- `error_code: 0` indica successo
- `error_code: 10032` indica token non valido o scaduto
- `result` contiene i dati specifici dell'endpoint

## Endpoint Scoperti

La discovery ha identificato oltre 200 endpoint tra v1 e v2. Quelli usati dal template Zabbix sono una selezione conservativa:

| Endpoint | Uso |
| --- | --- |
| `/miro/api/v1/login` | Autenticazione |
| `/miro/api/v1/debugmode/information` | CPU, memoria, uptime, firmware |
| `/miro/api/v1/cloud_service` | Stato cloud |
| `/miro/api/v1/connection_status` | Stato connessioni |
| `/miro/api/v1/quwan/deployment_progress` | Stato QuWAN |
| `/miro/api/v1/quwan/status` | Stato QuWAN |
| `/miro/api/v2/system/machine_info` | Info router |
| `/miro/api/v2/network_status` | Stato Internet |
| `/miro/api/v2/system/hardware_status` | Temperatura, uptime |
| `/miro/api/v2/network/ports` | Configurazione porte |
| `/miro/api/v2/network/ports_status` | Stato porte e throughput |
| `/miro/api/v2/debugmode/port_statistic` | Contatori switch |
| `/miro/api/v2/network/wan/status` | Stato WAN |
| `/miro/api/v2/clients` | Client connessi |
| `/miro/api/v2/firmware` | Firmware |
| `/miro/api/v2/load_balancing_status` | Multi-WAN |
| `/miro/api/v2/ddns/info` | DDNS |
| `/miro/api/v2/wireless/status` | Wi-Fi |
| `/miro/api/v2/wireless/band/status` | Bande Wi-Fi |
| `/miro/api/v2/wireless/vap/status` | VAP Wi-Fi |
| `/miro/api/v2/eventlogs` | Event log |

## Limitazioni

- Le API non sono documentate ufficialmente e potrebbero cambiare
- Alcuni endpoint restituiscono errori su firmware diversi
- `/miro/api/v1/laninfo` puo causare instabilita (HTTP 500 osservato)
- Il probe va eseguito con cautela: solo `GET`, con delay tra le richieste
