# SG Smart CSRmesh for Home Assistant

Én lysentitet for en eksisterende SG Smart LEDDim Smart Pill med Bluetooth-navn som begynner med `@MC`. Home Assistant bruker sin egen Bluetooth-integrasjon. Du trenger bryterens eksisterende nettverks-PIN og mesh-ID fra opptaket. Integrasjonen gjør ingen endringer i paring, grupper eller innstillinger på SG-utstyret.

## Installasjon

1. [Last ned repoet som ZIP](https://github.com/rikardljokjell-del/Stuelys-bt-ha/archive/refs/heads/main.zip) og pakk det ut.
2. Kopier hele mappen `custom_components/sg_smart_csrmesh` til `/config/custom_components/` på Home Assistant. Sjekk at `manifest.json` ligger direkte under `/config/custom_components/sg_smart_csrmesh/`.
3. Start **Home Assistant** på nytt. Home Assistant installerer `recsrmesh==0.3.0` automatisk. Bluetooth-integrasjonen må ha en aktiv adapter som støtter tilkobling og som når både veggbryteren og mottakeren.
4. Åpne **Innstillinger → Enheter og tjenester**. Velg den oppdagede **SG Smart CSRmesh**, eller velg **Legg til integrasjon** og søk etter navnet. Lukk SG-appen på telefonen så mottakeren er ledig.

```text
/config/custom_components/sg_smart_csrmesh/
├── __init__.py
├── config_flow.py
├── light.py
├── manifest.json
├── mesh.py
├── protocol.py
└── translations/
    ├── en.json
    └── nb.json
```

## Første test på lampen

1. Velg mottakerens navn og MAC-adresse. Skriv inn PIN-en og veggbryterens heksadesimale mesh-ID. Denne ID-en er avsenderen i bryterens datapakker. Den kan avvike fra de siste sifrene i mottakerens MAC-adresse.
2. Når **Trykk PÅ på veggbryteren** vises, gi PÅ-knappen et kort trykk. Trykk deretter **Send inn**. En fersk PÅ-melding fra den oppgitte bryteren må bestå HMAC-kontrollen. Meldingen gir Home Assistant riktig gruppe og steds-ID.
3. Se på taklampen. Start **Test AV** og se at den slukker. Start så **Test PÅ** og se at den tenner. Testen bruker samme gruppe som veggbryteren. Hvis bryteren styrer flere lamper, kan alle reagere.
4. Bekreft begge synlige endringer for å opprette lysentiteten. En ferdig BLE-skriving alene er utilstrekkelig som bekreftelse. I AV/PÅ-modus viser entiteten antatt tilstand fra siste HA-kommando eller mottatte AV/PÅ-trykk. Etter omstart står den som ukjent fram til neste kommando.

## Lysstyrke

Etter en vellykket AV/PÅ-test velger du **Konfigurer → Aktiver lysstyrke** på integrasjonen. Den ber om mottakerens navn og kontrollerer et autentisert svar med riktig navn og steds-ID. Deretter ber den denne mesh-noden om status. Først når begge svarene kommer, får den samme lysentiteten en lysstyrkekontroll.

Prøv for eksempel 30 % og deretter 70 %. Se på lampen ved begge nivåene. Integrasjonen sender et absolutt nivå på 1–100 %, leser nivået tilbake og melder feil ved avvik. Null sendes som AV. Med lysstyrke aktiv leses status også hvert andre minutt slik at Home Assistant kan fange opp endringer fra veggbryteren. Du kan slå av lysstyrkefunksjonen under **Konfigurer**.

## Hvis testen stopper

| Symptom | Hva du kan sjekke |
| --- | --- |
| Ingen mottaker i listen | Se etter mottakerens `@MC`-navn og tjeneste `FEF1` i Bluetooth-integrasjonens annonsemonitor. Kontroller rekkevidde og lukk SG-appen. |
| Oppsettet venter på PÅ | Bruk et kort PÅ-trykk mens oppsettssiden er åpen. Kontroller bryterens mesh-ID og PIN. De korte knappemeldingene kan ha skiftende BLE-adresser. |
| AV/PÅ gir BLE-feil | Åpne **Innstillinger → System → Logger** og søk etter `sg_smart_csrmesh`. Loggen viser mottaker, handling og feil fra BLE, for eksempel en manglende GATT-karakteristikk eller tidsavbrudd. |
| Skrivingen gikk gjennom, men lampen reagerte ikke | Avbryt testen. Kontroller valgt mottaker og at samme fysiske knapp faktisk styrer lampen. Et GATT-svar bekrefter bare overføringen til mottakeren. |
| Lysstyrketesten mangler svar | `FF11` er navnesvaret, `FF05` er status. AV/PÅ kan brukes selv om denne firmwareversjonen ikke svarer på forespørslene. |

## Hva opptakene og kildene viser

De fem BLE Radar-eksportene er annonseskann. Mottakeren annonserte seg som tilkoblingsbar med FEF1 i alle fem. Alle 105 ulike FEF1-datapayloadene i knappetestene besto HMAC-kontrollen med den oppgitte PIN-en. Tallet inkluderer videresendte varianter av samme melding. I hvileopptaket var mottakeren synlig, uten slike datapayloads.

Veggbryteren sendte kort `FF03` for AV/PÅ til samme gruppe i begge opptakene. Dim opp og ned brukte `FF23` med verdiene `01` og `02`, etterfulgt av `03` for stopp. Opptakene inneholder ingen direkte GATT-test fra Home Assistant og ingen rapportert absolutt lysstyrke. AV/PÅ bruker det observerte formatet med nye sekvens- og transaksjonsnumre. Absolutt lysstyrke bruker SG-referansens direkte `FF03` og statusforespørsel `FF04`. Fysisk funksjon på denne lampen må bekreftes lokalt.

SG-meldinger og GATT-fragmentering er beskrevet i [Homey-integrasjonens SG-protokoll](https://github.com/fiskentnt/com.sgsmart.csrmesh/blob/1a15c74b2a69c0f6b6a5d48eb2918f85b9bd5839/lib/sgProtocol.js) og [MeshBridge](https://github.com/fiskentnt/com.sgsmart.csrmesh/blob/1a15c74b2a69c0f6b6a5d48eb2918f85b9bd5839/lib/MeshBridge.js). Kryptering og autentisering kommer fra [recsrmesh 0.3.0](https://pypi.org/project/recsrmesh/0.3.0/), som bygger på [nkaminski/csrmesh](https://github.com/nkaminski/csrmesh).
