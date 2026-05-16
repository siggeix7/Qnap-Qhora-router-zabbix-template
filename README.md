# QNAP QuRouter Zabbix Template

Template Zabbix 7.0 per monitorare router QNAP QuRouter tramite REST API non documentate.

Il template e stato sviluppato e testato su QNAP QHora-301W con firmware QuRouter `2.7.1.048`. Usa le API web esposte dal frontend QuRouter sotto `/miro/api/v1/` e `/miro/api/v2/`.

## Compatibilita

| Componente | Versione |
| --- | --- |
| Zabbix | 7.0 |
| Router testato | QNAP QHora-301W |
| Firmware testato | QuRouter 2.7.1.048 |
| Metodo raccolta | REST API via HTTPS |
| Autenticazione | Login locale + Bearer token |

## File Principale

| File | Descrizione |
| --- | --- |
| `zabbix_template_qnap_qurouter_7.0.yaml` | Template importabile in Zabbix 7.0 |

## Documentazione Del Repository

| File | Descrizione |
| --- | --- |
| `CHANGELOG.md` | Storico delle versioni e modifiche principali |
| `CONTRIBUTING.md` | Linee guida per contributi e compatibility report |
| `SECURITY.md` | Note di sicurezza e dati da non pubblicare |
| `sources/` | Documentazione tecnica su API discovery e design del template |

## Funzionalita

- Login automatico su `/miro/api/v1/login`.
- Raccolta dati tramite item master `SCRIPT`.
- Dependent item per ridurre il numero di chiamate API.
- Nessuno storico sul master JSON aggregato.
- Monitoraggio multi-WAN.
- Discovery porte Ethernet fisiche.
- Discovery statistiche switch `swdev1..swdev6`.
- Discovery bande Wi-Fi.
- Grafici statici, prototipi di grafico LLD e dashboard host per Zabbix.
- Trigger per stato API, Internet, WAN, porte, temperatura, memoria, firmware e reboot.

## Metriche Monitorate

| Area | Metriche |
| --- | --- |
| Sistema | uptime, CPU load, temperatura CPU, memoria totale/usata/percentuale |
| Firmware | versione locale, ultima versione disponibile, upgrade disponibile |
| Rete | stato Internet, QuWAN cloud agent, load balancing active tier |
| Multi-WAN | stato link, IPv4, NCSI, throughput RX/TX |
| Porte Ethernet | stato up/down, link rate, MAC, throughput RX/TX, packet rate RX/TX |
| Switch | RX/TX byte rate, RX/TX errors, RX/TX dropped |
| Wi-Fi | modalita Wi-Fi, canale e bandwidth per banda |
| Client | numero totale client conosciuti |
| Log | numero totale eventi |

## Grafici E Dashboard

- Grafici statici per CPU/memoria, temperatura CPU, uso memoria, client/eventi e stati di salute.
- Prototipi di grafico per throughput WAN, throughput/packet rate/link rate Ethernet, statistiche switch e impostazioni radio Wi-Fi.
- Dashboard host `QuRouter overview` con pagine `Overview` e `Interfaces`.

## Import In Zabbix

1. Vai in `Data collection` > `Templates`.
2. Clicca `Import`.
3. Seleziona `zabbix_template_qnap_qurouter_7.0.yaml`.
4. Importa il template.
5. Associa il template all'host del router.
6. Configura le macro host obbligatorie.

## Macro Obbligatorie

| Macro | Esempio | Descrizione |
| --- | --- | --- |
| `{$QROUTER.URL}` | `https://192.168.1.1` | URL base del router |
| `{$QROUTER.USER}` | `admin` | Username locale QuRouter |
| `{$QROUTER.PASSWORD}` | secret | Password locale QuRouter, macro secret |

## Macro Opzionali

| Macro | Default | Descrizione |
| --- | --- | --- |
| `{$QROUTER.FORCE_LOGIN}` | `true` | Forza il login se esiste gia una sessione attiva |
| `{$QROUTER.INTERVAL}` | `1m` | Intervallo raccolta dati |
| `{$QROUTER.NODATA}` | `5m` | Timeout per trigger no-data |
| `{$QROUTER.CLIENTS.MAX.WARN}` | `100` | Soglia warning numero client |
| `{$QROUTER.CPU.LOAD.WARN}` | `80` | Soglia warning CPU load |
| `{$QROUTER.CPU.TEMP.WARN}` | `80` | Soglia warning temperatura CPU |
| `{$QROUTER.MEMORY.PUSED.WARN}` | `85` | Soglia warning memoria usata percentuale |
| `{$QROUTER.REBOOT.UPTIME.MIN}` | `600` | Uptime sotto cui rilevare un reboot |
| `{$QROUTER.QUWAN.AGENT.REQUIRED}` | `0` | Abilita trigger QuWAN agent down |
| `{$QROUTER.WAN.LINK.REQUIRED}` | `1` | Abilita trigger link down per WAN |
| `{$QROUTER.PORT.LINK.REQUIRED}` | `1` | Abilita trigger link down per porte WAN |
| `{$QROUTER.ETH.LINK.REQUIRED}` | `0` | Abilita trigger link down per porte Ethernet fisiche |
| `{$QROUTER.WAN.NCSI.OK}` | `0` | Valore NCSI considerato sano |
| `{$QROUTER.WAN.RX.MIN.WARN}` | `0` | Soglia minima RX WAN, disabilitata se 0 |
| `{$QROUTER.WAN.TX.MIN.WARN}` | `0` | Soglia minima TX WAN, disabilitata se 0 |
| `{$QROUTER.SWITCH.ERRORS.WARN}` | `0` | Abilita trigger su incremento errori/dropped switch |

## Macro Contestuali

Per abilitare trigger solo su porte specifiche puoi usare macro contestuali Zabbix.

| Esempio | Effetto |
| --- | --- |
| `{$QROUTER.ETH.LINK.REQUIRED:"2"}=1` | La porta Ethernet 2 deve restare up |
| `{$QROUTER.ETH.LINK.REQUIRED:"6"}=1` | La porta Ethernet 6 deve restare up |
| `{$QROUTER.WAN.LINK.REQUIRED:"swdev5"}=1` | La WAN su `swdev5` deve restare up |
| `{$QROUTER.PORT.LINK.REQUIRED:"5"}=1` | La porta WAN 5 deve restare up |
| `{$QROUTER.WAN.RX.MIN.WARN:"5"}=100000` | Warning se RX medio porta WAN 5 scende sotto 100 KBps circa |

## Porte QHora-301W

Il template assegna etichette leggibili alle porte discoverate.

| Porta | Etichetta |
| --- | --- |
| 1-4 | `1GbE port N` |
| 5-6 | `10GbE port N` |

Se il router espone un nome configurato, il template lo include nel nome item. Esempio: `10GbE port 5 - Open Fiber`.

## Trigger Inclusi

- API senza dati.
- Endpoint API falliti.
- Internet disconnesso.
- CPU load alta.
- Temperatura CPU alta.
- Flag temperatura CPU high.
- Memoria alta.
- Reboot rilevato.
- Cambio versione firmware.
- Upgrade firmware disponibile.
- Numero client alto.
- QuWAN cloud agent non attivo, disabilitato di default.
- Link WAN down.
- NCSI WAN non sano.
- Cambio IPv4 WAN.
- Link porta WAN down.
- Link porta Ethernet down, disabilitato di default.
- Incremento errori/dropped switch, disabilitato di default.
- Cambio canale o bandwidth Wi-Fi.

## Note Di Sicurezza

- Non committare file con credenziali, token o cookie.
- Usa macro secret per `{$QROUTER.PASSWORD}`.
- Il template usa `{$QROUTER.FORCE_LOGIN}=true` di default per ottenere sempre un token API.
- Il login forzato puo chiudere sessioni web QuRouter gia aperte.
- Le API QuRouter usate non sono documentate ufficialmente da QNAP e potrebbero cambiare con aggiornamenti firmware.

## Endpoint Usati

| Endpoint | Uso |
| --- | --- |
| `/miro/api/v1/login` | Login e token |
| `/miro/api/v1/debugmode/information` | CPU, memoria, uptime, firmware |
| `/miro/api/v1/cloud_service` | Stato cloud service |
| `/miro/api/v1/connection_status` | Stato connessioni |
| `/miro/api/v1/quwan/deployment_progress` | Stato deployment QuWAN |
| `/miro/api/v1/quwan/status` | Stato QuWAN |
| `/miro/api/v2/system/machine_info` | Informazioni router |
| `/miro/api/v2/network_status` | Stato Internet |
| `/miro/api/v2/system/hardware_status` | Temperatura e uptime |
| `/miro/api/v2/network/ports` | Configurazione porte |
| `/miro/api/v2/network/ports_status` | Stato porte e throughput |
| `/miro/api/v2/debugmode/port_statistic` | Contatori switch |
| `/miro/api/v2/network/wan/status` | Stato WAN |
| `/miro/api/v2/clients` | Client |
| `/miro/api/v2/firmware` | Firmware |
| `/miro/api/v2/load_balancing_status` | Multi-WAN/load balancing |
| `/miro/api/v2/ddns/info` | DDNS |
| `/miro/api/v2/wireless/status` | Wi-Fi |
| `/miro/api/v2/wireless/band/status` | Bande Wi-Fi |
| `/miro/api/v2/wireless/vap/status` | VAP Wi-Fi |
| `/miro/api/v2/eventlogs` | Event log |

## Troubleshooting

| Problema | Possibile causa | Soluzione |
| --- | --- | --- |
| Login OK ma nessun token | Sessione QuRouter gia attiva | Imposta `{$QROUTER.FORCE_LOGIN}=true` |
| `Token is invalid` | Token scaduto o login fallito | Verifica macro user/password e connettivita |
| Nessun dato sul master | Script fallito | Controlla `Latest data` e log Zabbix server/proxy |
| Falsi positivi link Ethernet | Porta non sempre usata | Lascia `{$QROUTER.ETH.LINK.REQUIRED}=0` o usa macro contestuali |
| Falsi positivi NCSI | Valore sano diverso dal default | Regola `{$QROUTER.WAN.NCSI.OK}` |

## Stato Del Progetto

Template creato tramite reverse engineering del frontend QuRouter e validato con raccolta dati reale su QHora-301W.

Contributi, test su altri modelli QNAP e pull request sono benvenuti.
