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
python3 sources/tools/discover_qnap_api.py --base-url https://<ROUTER_IP> --output-dir ~/qrouter_exports/discovery

# 3. Prova gli endpoint con autenticazione
python3 sources/tools/authenticated_probe_qnap.py --base-url https://<ROUTER_IP> --credentials credentials.txt --output-dir ~/qrouter_exports/probe --zabbix-candidates

# 4. Esporta uno snapshot Markdown della configurazione del router
python3 sources/tools/export_qrouter_config_md.py

# Oppure passando gia URL, utente e cartella output
python3 sources/tools/export_qrouter_config_md.py --base-url https://<ROUTER_IP> --username admin --output-dir ~/qrouter_exports --extended-discovery

# Se ometti --output-dir in modalita interattiva, lo script chiede la cartella al prompt
```

### Export Configurazione Markdown

`export_qrouter_config_md.py` esegue un login locale QuRouter, interroga endpoint API `GET` e genera due file nella cartella scelta al prompt o passata con `--output-dir`:

- `qrouter_config_<host>_<timestamp>.md`: report Markdown leggibile e sintetico organizzato per sistema, WAN/failover, LAN/VLAN/bridge, DHCP, Wi-Fi con VLAN associate, rotte statiche, NAT, VPN e sicurezza
- `qrouter_config_<host>_<timestamp>.json`: raccolta JSON completa degli endpoint interrogati, senza redazione dei campi di configurazione

La modalita interattiva chiede IP/URL del router, username, password, cartella di output, se forzare il login e se eseguire la discovery estesa degli endpoint dal frontend. Se la cartella non viene indicata, in modalita non interattiva il default e `~/qrouter_exports`, fuori dal repository. La discovery estesa scarica anche i chunk JavaScript dinamici del frontend QuRouter, ricostruisce la mappa endpoint minificata e aggiunge altri endpoint `GET` rilevati, escludendo path dinamici, instabili, download/export o parole associate ad azioni potenzialmente modificanti.

Il Markdown privilegia le informazioni utili per ricostruire manualmente la configurazione:

- failover/load balancing WAN con tier, weight, failback e stato delle porte
- interfacce LAN, VLAN, bridge, tag/untag e servizi DHCP
- SSID Wi-Fi, bande, sicurezza e VLAN/interfaccia collegata
- rotte statiche IPv4/IPv6 e policy route
- server VPN QBelt, L2TP, OpenVPN, WireGuard e utenti configurati/online
- NAT port forwarding, DDNS, accesso amministrativo e service port

Gli endpoint raccolti ma non riassunti non vengono piu espansi automaticamente nel Markdown, per evitare blocchi di dati poco leggibili. Restano sempre nel JSON completo affiancato. Se serve includere anche i dettagli grezzi nel Markdown si puo usare `--include-raw-json`.

Quando usi `--extended-discovery`, nella stessa cartella di output vengono create anche:

- `raw/`: copia locale degli asset frontend scaricati dal router, inclusi HTML, JavaScript e CSS
- `artifacts/`: JSON intermedi della discovery, come endpoint trovati e risposte HTTP del frontend

Queste directory sono necessarie per analizzare le API non documentate, ma non vengono piu generate dentro il repository. Possono contenere dettagli del router e della rete: trattale come dati privati.

Di default il Markdown non include blocchi JSON raw: le risposte complete sono nel file `.json` affiancato.

Il report e uno snapshot documentale utile per change tracking e riconfigurazione manuale futura; non e un backup ufficiale ripristinabile.

## Note Di Sicurezza

- Questi endpoint API **non sono documentati ufficialmente da QNAP** e potrebbero cambiare con aggiornamenti firmware
- Usare solo `GET` per il monitoraggio. Qualsiasi `POST`/`PUT`/`DELETE` puo modificare la configurazione del router
- Il login con `force=true` chiude le sessioni web eventualmente gia aperte
- Non committare mai file con credenziali, token o cookie
- I file Markdown e JSON generati dai probe/export contengono dati sensibili della tua rete, inclusi campi di configurazione non redatti: non pubblicarli
