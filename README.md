# SG Smart CSRmesh for Home Assistant

Én lysentitet for en eksisterende SG Smart LEDDim Smart Pill med Bluetooth-navn som begynner med `@MC`. Home Assistant bruker sin egen Bluetooth-integrasjon. Du trenger bryterens eksisterende nettverks-PIN og mesh-ID fra opptaket. Integrasjonen gjør ingen endringer i paring, grupper eller innstillinger på SG-utstyret.

## Installasjon

På mobil med Zipper i Studio Code Server kan du laste opp installasjonsfilen til `/config/custom_components/` og velge **Extract** på ZIP-filen. Zipper lager mappen `sg_smart_csrmesh` med `manifest.json` rett inni. Flytt en eventuell eldre `sg_smart_csrmesh`-mappe ut av `custom_components` før du pakker ut. Start Home Assistant på nytt og fortsett i **Enheter og tjenester**. [Last ned installasjonsfilen](https://github.com/rikardljokjell-del/Stuelys-bt-ha/releases/latest/download/sg_smart_csrmesh.zip)

### Manuell kopiering

1. [Last ned repoet som ZIP](https://github.com/rikardljokjell-del/Stuelys-bt-ha/archive/refs/heads/main.zip) og pakk det ut.
2. Kopier hele mappen `custom_components/sg_smart_csrmesh` til `/config/custom_components/` på Home Assistant. Sjekk at `manifest.json` ligger direkte under `/config/custom_components/sg_smart_csrmesh/`.
3. Start **Home Assistant** på nytt. Home Assistant installerer `recsrmesh==0.3.0` automatisk. Bluetooth-integrasjonen må ha en aktiv adapter som støtter tilkobling og som når både veggbryteren og mottakeren.
4. Åpne **Innstillinger → Enheter og tjenester**. Velg den oppdagede **SG Smart CSRmesh**, eller velg **Legg til integrasjon** og søk etter navnet. Lukk SG-appen på telefonen så mottakeren er ledig.

```text
/config/custom_components/sg_smart_csrmesh/
├── __init__.py
├── advertise.py
├── button.py
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

1. Velg mottakerens navn og MAC-adresse. Skriv inn PIN-en og veggbryterens heksadesimale mesh-ID. Denne ID-en er avsenderen i bryterens datapakker. Den kan avvike fra de siste sifrene i mottakerens MAC-adresse. Under **Sendemåte** velger du hvordan Home Assistant skal sende kommandoene.
2. Når **Trykk PÅ på veggbryteren** vises, gi PÅ-knappen et kort trykk. Trykk deretter **Send inn**. En fersk PÅ-melding fra den oppgitte bryteren må bestå HMAC-kontrollen. Meldingen gir Home Assistant riktig gruppe og steds-ID.
3. Sørg for at taklampen lyser. Start **Test AV** og deretter **Test PÅ** mens du ser på lampen. Testen bruker samme gruppe som veggbryteren. Hvis bryteren styrer flere lamper, kan alle reagere.
4. Bekreft begge synlige endringer for å opprette lysentiteten. Hvis en av testene feilet, la krysset stå tomt og trykk **Send inn**. Med GATT får du tilbud om å prøve direkte styring når mottakeren kan identifiseres. Ved bekreftelse lagres sendemåten lampen reagerte på.

I AV/PÅ-modus viser entiteten antatt tilstand fra siste HA-kommando eller mottatte AV/PÅ-trykk. Etter omstart står den som ukjent fram til neste kommando.

## Lysstyrke

Etter en vellykket AV/PÅ-test velger du **Konfigurer** på integrasjonen. Med BLE-annonser får du to valg:

- **Lysstyrke i prosent (skyveknapp)** prøver 30 % og 70 % i den korte `FF03`-gruppekommandoen fra AV/PÅ. Hvis lampen reagerer på begge, får den eksisterende lysentiteten en skyveknapp. Home Assistant viser sist sendte lysstyrke som antatt nivå. En mottatt dimmekommando fra veggbryteren gjør nivået ukjent igjen.
- **Dim opp og ned (knapper)** prøver `FF23` fra dimmeopptakene. Hvert trykk sender opp eller ned, lar lampen dimme en kort stund og sender så stopp. Etter bestått test vises **Dim opp** og **Dim ned** under den samme enheten.

Med GATT velger du **Konfigurer → Aktiver lysstyrke**. Da må mottakeren oppgi navn og svare på en statusforespørsel før skyveknappen aktiveres. Home Assistant leser status etter en kommando og hvert andre minutt. Lysstyrke null sendes som AV i begge prosentmodusene.

## Hvis testen stopper

| Symptom | Hva du kan sjekke |
| --- | --- |
| Ingen mottaker i listen | Se etter mottakerens `@MC`-navn og tjeneste `FEF1` i Bluetooth-integrasjonens annonsemonitor. Kontroller rekkevidde og lukk SG-appen. |
| Oppsettet venter på PÅ | Bruk et kort PÅ-trykk mens oppsettssiden er åpen. Kontroller bryterens mesh-ID og PIN. De korte knappemeldingene kan ha skiftende BLE-adresser. |
| AV/PÅ gir BLE-feil | Åpne **Innstillinger → System → Logger** og søk etter `sg_smart_csrmesh`. Loggen viser mottaker, handling og feil fra BLE, for eksempel en manglende GATT-karakteristikk eller tidsavbrudd. |
| Skrivingen gikk gjennom, men lampen reagerte ikke | Fullfør de to teststegene og la bekreftelsesboksen stå tom. Da får du prøve direkte styring. Et GATT-svar bekrefter bare overføringen til mottakeren. |
| Lysstyrketesten mangler svar | `FF11` er navnesvaret, `FF05` er status. AV/PÅ kan brukes selv om denne firmwareversjonen ikke svarer på forespørslene. |

Under **Prøv direkte styring** kan du la **Les lampestatus etter hver test** stå på. Etter de to testene viser veiviseren rapportert lysstyrke eller feilen for hver lesing. `FF05: 0 %` betyr at mottakeren rapporterte AV. Hvis navne- eller statusforespørselen får tidsavbrudd, viser feilmeldingen antall GATT-varsler, autentiserte mesh-meldinger og ekko av Home Assistants egne meldinger. Send gjerne skjermbildet av dette resultatet ved feil. PIN og pakkedata er utelatt fra diagnosen.

Hvis GATT-testen fullføres uten respons fra lampen, kan du velge **BLE-annonser (som veggbryteren)**. Da sender Home Assistant AV/PÅ til samme mesh-gruppe i FEF1-annonsedata via det lokale Bluetooth-kortet. Det krever en Linux-adapter med støtte for annonsering via BlueZ. Lampens respons må bekreftes visuelt. [BlueZ Advertising API](https://bluez.readthedocs.io/en/latest/advertising-api/)

Du kan også velge **Bluetooth GATT uten kvittering** dersom mottakeren støtter den skrivemodusen. Meldingen ved tidsavbrudd viser avsender og opcode for de vanligste autentiserte meldingene.

## Hva opptakene og kildene viser

De fem BLE Radar-eksportene er annonseskann. Mottakeren annonserte seg som tilkoblingsbar med FEF1 i alle fem. Alle 105 ulike FEF1-datapayloadene i knappetestene besto HMAC-kontrollen med den oppgitte PIN-en. Tallet inkluderer videresendte varianter av samme melding. I hvileopptaket var mottakeren synlig, uten slike datapayloads.

Veggbryteren sendte kort `FF03` for AV/PÅ til samme gruppe i begge opptakene. Dim opp og ned brukte `FF23` med verdiene `01` og `02`, etterfulgt av `03` for stopp. AV/PÅ via BLE-annonser er bekreftet på lampen. Opptakene viser relative dimmekommandoer, så absolutt lysstyrke med kort `FF03` må prøves på lampen. GATT-styring bruker SG-referansens direkte `FF03` og statusforespørsel `FF04`.

SG-meldinger og GATT-fragmentering er beskrevet i [Homey-integrasjonens SG-protokoll](https://github.com/fiskentnt/com.sgsmart.csrmesh/blob/1a15c74b2a69c0f6b6a5d48eb2918f85b9bd5839/lib/sgProtocol.js) og [MeshBridge](https://github.com/fiskentnt/com.sgsmart.csrmesh/blob/1a15c74b2a69c0f6b6a5d48eb2918f85b9bd5839/lib/MeshBridge.js). Kryptering og autentisering kommer fra [recsrmesh 0.3.0](https://pypi.org/project/recsrmesh/0.3.0/), som bygger på [nkaminski/csrmesh](https://github.com/nkaminski/csrmesh).
