# Zabbix Template Design

Come e perche e stato progettato il template Zabbix per il QNAP QuRouter.

## Architettura Di Raccolta

### Master Item + Dependent Items

Il template usa un pattern "master + dependent" per minimizzare le chiamate al router:

```
[SCRIPT] Master Item "QuRouter: API aggregate JSON"
    |
    +-- [DEPENDENT] qrouter.system.uptime
    +-- [DEPENDENT] qrouter.system.cpu.load
    +-- [DEPENDENT] qrouter.system.cpu.temp
    +-- [DEPENDENT] qrouter.system.memory.total
    +-- [DEPENDENT] qrouter.system.memory.used
    +-- [DEPENDENT] qrouter.system.memory.pused
    +-- [DEPENDENT] qrouter.firmware.local
    +-- [DEPENDENT] qrouter.firmware.latest
    +-- [DEPENDENT] qrouter.firmware.upgrade_available
    +-- [DEPENDENT] qrouter.internet.status
    +-- [DEPENDENT] qrouter.quwan.agent
    +-- [DEPENDENT] qrouter.lb.active_tier
    +-- [DEPENDENT] qrouter.clients.total
    +-- [DEPENDENT] qrouter.events.total
    +-- [DEPENDENT] qrouter.wifi.mode
    +-- [DEPENDENT] qrouter.wifi.bands
    +-- [DEPENDENT] qrouter.wan.list
    +-- [DEPENDENT] qrouter.ports.list
    +-- [DEPENDENT] qrouter.switch.stats
    +-- [DEPENDENT] qrouter.api.failed
```

Vantaggi:
- **Una sola chiamata HTTP** al router per intervallo di raccolta
- Il master item usa `history: '0'` per non salvare lo storico del JSON raw
- I dependent item estraggono valori con preprocessing JSONPath
- `qrouter.api.failed` conta gli endpoint falliti e ospita il trigger `nodata()`

### Perche Non HTTP Agent Item

Zabbix supporta item di tipo `HTTP agent`, ma per il QuRouter serve:
1. Login `POST` per ottenere il token
2. Riutilizzo del token su molteplici `GET`
3. Gestione del caso in cui il token scada o una sessione esista gia

Uno script `POST`/`GET` personalizzato gestisce tutto questo in un'unica esecuzione.

## Discovery

### LLD Rule

Il template contiene 5 regole di low-level discovery:

| Discovery Key | Macro | Cosa scopre |
| --- | --- | --- |
| `qrouter.discovery.wan` | `{#IFNAME}`, `{#WANLABEL}` | Interfacce WAN logiche |
| `qrouter.discovery.wan_ports` | `{#PORT}`, `{#PORTDISPLAY}` | Porte fisiche usate come WAN |
| `qrouter.discovery.eth_ports` | `{#PORT}`, `{#PORTDISPLAY}`, `{#PORTSPEED}` | Porte Ethernet fisiche |
| `qrouter.discovery.switch_port_stats` | `{#IFACE}`, `{#PORT}`, `{#PORTDISPLAY}` | Contatori switch interni |
| `qrouter.discovery.wifi_bands` | `{#BAND}` | Bande Wi-Fi |

### Etichette Leggibili

Per distinguere le porte del QHora-301W (4x1GbE + 2x10GbE), il template usa preprocessing JavaScript nelle LLD macro:

- Porte 1-4: etichettate come `1GbE port N`
- Porte 5-6: etichettate come `10GbE port N`
- Se disponibile, viene incluso il nome configurato (es. `WAN-BACKUP`, `Open Fiber`)

Esempio di nome item risultante:
- `QuRouter Ethernet 1GbE port 2 - LAN1 (MNG): Link rate`
- `QuRouter Ethernet 10GbE port 5 - Open Fiber: Link rate`

## Visualizzazione

Il template include grafici e una dashboard host per usare direttamente i dati raccolti dopo l'import:

- Grafici statici top-level per carico CPU/memoria, temperatura, uso memoria, client/eventi e stati di salute.
- Prototipi di grafico nelle discovery per throughput WAN, throughput/packet rate/link rate Ethernet, byte rate ed errori/dropped switch, canale/bandwidth Wi-Fi.
- Dashboard `QuRouter overview` con pagina `Overview` per lo stato generale e pagina `Interfaces` per i grafici LLD.

I grafici fanno riferimento solo a item numerici gia presenti nel template; non aggiungono chiamate API o dependent item.

## Trigger

### Trigger Semplici

| Trigger | Condizione | Default |
| --- | --- | --- |
| API senza dati | `nodata()` su `qrouter.api.failed` | 5m |
| Endpoint API falliti | `last() > 0` su `qrouter.api.failed` | enabled |
| Internet disconnesso | `find() <> "up"` | enabled |
| CPU load alta | `last() > {$QROUTER.CPU.LOAD.WARN}` | 80% |
| Temperatura CPU alta | `last() > {$QROUTER.CPU.TEMP.WARN}` | 80C |
| Flag temperatura CPU high | `last() = 1` | enabled |
| Memoria alta | `last() > {$QROUTER.MEMORY.PUSED.WARN}` | 85% |
| Reboot rilevato | `last(uptime) < {$QROUTER.REBOOT.UPTIME.MIN}` | 600s |
| Cambio versione firmware | `last() <> last(#2)` | enabled |
| Upgrade firmware disponibile | `last() = 1` | enabled |
| Numero client alto | `last() > {$QROUTER.CLIENTS.MAX.WARN}` | 100 |
| Cambio canale/band Wi-Fi | `last() <> last(#2)` | enabled |

### Trigger Disabilitati Di Default

Questi trigger sono inclusi ma disabilitati, per evitare falsi positivi su porte non critiche:

| Trigger | Macro di controllo | Default |
| --- | --- | --- |
| QuWAN agent non attivo | `{$QROUTER.QUWAN.AGENT.REQUIRED}` | 0 (off) |
| Link porta Ethernet down | `{$QROUTER.ETH.LINK.REQUIRED:"{#PORT}"}` | 0 (off) |
| Incremento errori switch | `{$QROUTER.SWITCH.ERRORS.WARN}` | 0 (off) |
| Soglia minima RX WAN | `{$QROUTER.WAN.RX.MIN.WARN:"{#PORT}"}` | 0 (off) |
| Soglia minima TX WAN | `{$QROUTER.WAN.TX.MIN.WARN:"{#PORT}"}` | 0 (off) |

Per abilitarli su porte specifiche si usano **macro contestuali**:

```
{$QROUTER.ETH.LINK.REQUIRED:"2"}=1
{$QROUTER.ETH.LINK.REQUIRED:"6"}=1
{$QROUTER.WAN.LINK.REQUIRED:"swdev5"}=1
```

### Perche `diff()` Non Va Usato

Zabbix 7.0 non supporta `diff()` su item senza storico. Il master item ha `history: '0'`, quindi:

- `diff()` -> errore di import
- Sostituito con `last() <> last(#2)` per rilevare cambiamenti

### Perche `nodata()` Va Sul Dependent Item

Il master item ha `history: '0'`, quindi `nodata()` non puo valutarlo. La soluzione:

- `qrouter.api.failed` e un dependent item con `history` abilitata
- Il trigger `nodata()` punta a questo item
- Se il master fallisce, `qrouter.api.failed` non riceve aggiornamenti e il trigger scatta

## Preprocessing

### JSONPath

Ogni dependent item usa JSONPath per estrarre il valore dal JSON aggregato. Esempio:

```
JSONPath: $.system.uptime
```

### Multiplier

Il link rate delle porte e espresso in Mbps nelle API. Per convertirlo in bps (unita standard Zabbix per interfaccia di rete):

```
MULTIPLIER: 1000000
```

### JavaScript LLD

Le LLD rule usano preprocessing JavaScript per:
- Normalizzare i nomi delle porte
- Aggiungere etichette leggibili (`1GbE`, `10GbE`)
- Includere nomi configurati quando disponibili

## Macro

### Obbligatorie

| Macro | Descrizione |
| --- | --- |
| `{$QROUTER.URL}` | URL base del router (es. `https://192.168.1.1`) |
| `{$QROUTER.USER}` | Username locale |
| `{$QROUTER.PASSWORD}` | Password locale (macro secret) |

### Opzionali

| Macro | Default | Descrizione |
| --- | --- | --- |
| `{$QROUTER.FORCE_LOGIN}` | `true` | Forza il login se esiste gia una sessione |
| `{$QROUTER.INTERVAL}` | `1m` | Intervallo di raccolta |
| `{$QROUTER.NODATA}` | `5m` | Timeout trigger no-data |
| `{$QROUTER.CPU.LOAD.WARN}` | `80` | Soglia CPU load % |
| `{$QROUTER.CPU.TEMP.WARN}` | `80` | Soglia temperatura CPU |
| `{$QROUTER.MEMORY.PUSED.WARN}` | `85` | Soglia memoria % |
| `{$QROUTER.CLIENTS.MAX.WARN}` | `100` | Soglia numero client |
| `{$QROUTER.REBOOT.UPTIME.MIN}` | `600` | Uptime minimo per trigger reboot |
| `{$QROUTER.WAN.LINK.REQUIRED}` | `1` | Trigger link WAN down |
| `{$QROUTER.PORT.LINK.REQUIRED}` | `1` | Trigger link porta WAN down |
| `{$QROUTER.ETH.LINK.REQUIRED}` | `0` | Trigger link porta Ethernet down |
| `{$QROUTER.WAN.NCSI.OK}` | `0` | Valore NCSI sano |
| `{$QROUTER.QUWAN.AGENT.REQUIRED}` | `0` | Trigger QuWAN agent |
| `{$QROUTER.SWITCH.ERRORS.WARN}` | `0` | Trigger errori switch |
| `{$QROUTER.WAN.RX.MIN.WARN}` | `0` | Soglia minima RX WAN |
| `{$QROUTER.WAN.TX.MIN.WARN}` | `0` | Soglia minima TX WAN |

## Compatibilita

- Zabbix 7.0 (testato)
- QNAP QHora-301W con firmware QuRouter 2.7.1.048
- Potrebbe funzionare su altri modelli QuRouter, ma non testato
