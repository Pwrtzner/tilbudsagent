# Tilbudsagent (v0.2)

Henter ugens tilbud fra Tjek (eTilbudsavis), gemmer dem i SQLite og anbefaler, hvilke butikker der er værd at køre til, når kørsel (kr/km, tur/retur) trækkes fra besparelsen. Nu med en app til dashboard, varer og indstillinger.

## Kom i gang
1. Læg `tilbudsagent.py`, `webapp.py`, `app.html`, `config.toml` og `varer.csv` i samme mappe. Python 3.11+ uden pakker; på 3.10 kræves `pip install tomli`.
2. `python tilbudsagent.py app` starter appen og åbner `http://localhost:8765` i browseren. Appen kører kun på din egen computer. Stop den med Ctrl+C.
3. I appen:
   - **Indstillinger:** skriv din adresse og tryk Find, ret kørselspris, butikker (afstand, zone, Tjek-navn) og rabatgrænser.
   - **Varer:** tilføj og ret varer. Udfyld `Normalpris`, så rabatterne bliver præcise.
   - **Hent tilbud** (knappen øverst) henter nye tilbud. **Tilbud** viser alle aktive tilbud og lader dig indtaste tilbud manuelt (fx ABC Lavpris).
   - **Indlæs demodata** (under Indstillinger) fylder syntetiske priser i, så du kan se, hvordan appen virker. Fjern dem igen, før du bruger den på rigtigt.
4. Ugentlig kørsel uden appen: `python tilbudsagent.py uge` (henter + laver rapport), fx som planlagt opgave.

`config.toml` og `varer.csv` bruges kun som startværdier første gang. Bagefter ligger indstillinger og varer i `priser.db` og ændres i appen.

## Regnemodel
- Afstande er én vej. Kørsel = 2 × km × kr/km pr. zone, målt til den fjerneste valgte butik i zonen.
- Zoner (antaget): `lokal` = Netto, Lidl, SuperBrugsen, Matas, REMA 1000, 365discount (6,6–8,2 km); `spar` (13,8 km); `fjern` = MENY, føtex, ABC Lavpris (23,3–28,2 km).
- Zoner du alligevel kører til (standard: `lokal`) koster 0 kr i kørsel. Det slås til/fra under Indstillinger.
- Pr. uge vælger agenten den butiksmængde, der giver højest netto = besparelse − kørsel − pris pr. butik. Besparelse = (normalpris − tilbudspris) × mængde.
- Lagerkøb: nær bundpris og kraftigt under normalpris giver `maks. lager` i stedet for den normale købsmængde.

## Kendte begrænsninger
- **Tjek-endpointet er ikke testet live** (udviklet uden netadgang til Tjek). Det er udokumenteret, og kilder er uenige om, om en nøgle kræves. Kør Hent tilbud én gang: Overblik viser, hvis kald fejler, eller forhandlere ikke matcher en butik (ret så «Tjek-navn»).
- Adressen slås op hos OpenStreetMap (Nominatim) og kræver internet. DAWA, den gamle danske adresse-API, blev lukket 1. juli 2026. Kan opslaget ikke bruges, kan koordinater indtastes direkte.
- Afstande til butikkerne indtastes stadig manuelt; de beregnes ikke ud fra adressen.
- Tilbudsaviser viser kun **kampagnepriser**; Netto har ingen førpris. Uden `normalpris` estimeres den som typisk tilbudspris og undervurderes.
- "Køb 2 for …" og "kun med app" opdages kun som advarsel (⚠), ikke som genberegnet pris.
- Tilbud gælder kæden, ikke den enkelte butik. Tjek Tjeks brugsvilkår, før du kører den fast.

## Opdatering v0.3

- **Tydelig hente-bjælke:** under hentning vises en blå bjælke øverst med fremdrift ("søgning 7 af 16"), antal fundne tilbud og en statuslinje. Knappen "Hent tilbud" er deaktiveret og viser "Henter …". Når den er færdig, vises en grøn (eller rød ved fejl) besked.
- **Mærkevalg pr. vare:** hver vare er enten *Alle mærker* (generisk; du kan angive "Undgå mærker") eller *Kun bestemte mærker eller produkter* (fx «heinz ketchup»). Vil du have både din faste vare og et billigt alternativ, så tilføj varen to gange.
- **Matching kun på tilbuddets overskrift** (ikke beskrivelsen), så der kommer færre falske match. Ved ændring af en vare ryddes gamle ikke-matchende tilbud automatisk.
- **Pakkestørrelse for stk gættes ikke længere:** ukendt størrelse giver "ukendt" enhedspris og tæller ikke med i turen.
- **Urealistiske rabatter** (over `regler.max_rabat`, standard 60 %) ignoreres og markeres i Tilbud.
- **ABC Lavpris findes på Tjek** og hentes automatisk; manuelle priser for butikker med Tjek-data droppes.
- Python 3.10 kræver `pip install tomli`; 3.11+ kræver ingenting.

## Windows-app (v0.4)

- `Tilbudsagent.exe` bygges automatisk af GitHub Actions (`.github/workflows/byg-windows.yml`). Giv en version et tag, fx `git tag v0.4.0 && git push --tags`, så ligger exe'en under Releases. Workflowet kan også køres manuelt (Actions → Byg Windows-app → Run workflow). Skriv et versions-tag (fx v0.4.0) i feltet for at udgive en release, eller lad det stå tomt for kun at få filen som artifact.
- Bygningen kører en røgtest: exe'en startes, API'et kaldes, og den afsluttes.
- Pakket app gemmer data i `%APPDATA%\Tilbudsagent`. Kørt som script (`python tilbudsagent.py`) ligger data ved siden af scriptet som før. Miljøvariablen `TILBUDSAGENT_DATA` kan pege et andet sted hen.
- Uden argumenter starter `tilbudsagent.py` selve appen.
- Se `TESTERE.md` for en vejledning til testere.

## Historik (v0.5)

- Hvert tilbud, der hentes fra Tjek, gemmes uændret i tabellen `raa` (også tilbud, der ikke passer til dine varer lige nu). Dine varers priser (`obs`) afledes herfra og genopbygges automatisk, når en vare eller en butik rettes, og ved opstart. Nye varer får dermed historik fra de tilbud, der allerede er set.
- Tilbud fra før v0.5 ligger fortsat i `obs`; `raa` fyldes fra og med første hentning i v0.5.
- Appen henter selv tilbud, når der er gået over 20 timer siden sidste vellykkede hentning, mens den er åben og adressen er sat (kan slås fra under Indstillinger).
- Eksportér komplet (`/api/eksport?historik=1`) tager alle gemte tilbud og manuelle priser med. Import flettes uden dubletter.

## Steder og afstande (v0.6)

- **Fast hjem:** hjemmeadressen er udgangspunktet. Afstandene du har skrevet i Indstillinger → Butikker bruges som før. Slå «Find afstande automatisk» til for i stedet at få nærmeste butik i hver kæde (kæder markeret «Fast» beholder din egen afstand).
- **Jeg er et andet sted:** knappen øverst. Skriv en adresse, så finder appen nærmeste butik i hver kæde og vejafstanden dertil, og regner ugens tur fra dér. Zoner afgøres af afstand (grænserne kan ændres), og kørsel til «lokal» zone kan regnes som gratis, hvis du alligevel handler dér. Kæder der ikke findes inden for 60 km udelades.
- **Gemt én gang:** fundne butikker og afstande gemmes pr. sted (tabellen `afstand`) og slås kun op igen efter 180 dage (30 dage for kæder, der ikke blev fundet).
- **Kilder:** butikker fra OpenStreetMap (Overpass), kørselsafstand fra OSRM's gratis demoserver; kan vejafstand ikke hentes, bruges luftlinje × 1,3 (markeret «ca.»). Begge er delte, gratis tjenester: appen spørger kun, når noget mangler.
- Ligger det andet sted langt fra hjem, henter «Hent tilbud» også tilbud omkring det sted.
- Databasen: rå tilbud gemmes slanke (kun brugte felter), og tilbud der sidst er set for over 730 dage siden slettes (`regler.raa_dage`). Dine afledte priser bevares. Databasestørrelsen vises nederst i appen.

### v0.6.1

- Hjemmeadressen har sit eget kort i Indstillinger med knappen «Brug som hjemmeadresse», så den ikke afhænger af «Gem indstillinger» nederst.
- Flyttes hjemmeadressen mere end 0,5 km, skifter appen til automatiske afstande (de indtastede hørte til det gamle sted) og finder butikkerne med det samme.
- Butikstabellen viser én afstand pr. butik: den fundne (med adresse) eller den indtastede. «Indtast selv» låser en bestemt butik til din egen afstand.
- Butiksopslaget kører i baggrunden og viser fremdrift i tre trin, resultat og hvilke kæder der ikke blev fundet.

## Android-app (v0.7)

- **Samme kode som på pc.** Android-appen (`android/`) er en tynd skal: Python-serveren (`tilbudsagent.py`, `webapp.py`, `steder.py`) kører inde i appen via Chaquopy, og brugerfladen (`app.html`) vises i en WebView. Der er ikke to kodebaser; Gradle kopierer filerne fra repoets rod ved hver bygning.
- **Mobil-layout:** på små skærme bliver tabeller til kort, knapper og felter er større, og dialoger fylder hele bredden.
- **GPS:** «Jeg er et andet sted» har knappen «Brug min GPS-position». Appen spørger om lokationstilladelse første gang.
- **Data:** databasen ligger i appens private mappe på telefonen. Eksport og import (Indstillinger → Sikkerhedskopi) gemmer filen i `Download/Tilbudsagent` og læser fra filvælgeren, så historik kan flyttes mellem pc og telefon.
- **Bygning:** `.github/workflows/byg.yml` bygger både `Tilbudsagent.exe` og `Tilbudsagent.apk`, røgtester APK'en på en Android-emulator (appen startes, og serveren kaldes) og lægger begge på samme release.
- **Signering:** APK'en signeres med en fast nøgle fra GitHub-hemmelighederne `KEYSTORE_BASE64` og `KEYSTORE_KODE`. Samme nøgle skal bruges hver gang; ellers kan telefonen ikke opdatere appen, kun geninstallere den.
- Kræver Android 10 eller nyere. Baggrundshentning er ikke pålidelig på Android: appen henter, når den åbnes og der er gået over et døgn.

### v0.8.1

- **Rettelser udløber.** En rettelse gælder til tilbuddets sidste dag og forsvinder så fra listen «Rettelser og skjulte tilbud». En helt ny tilbudsavis, der starter efter udløbet, får ikke rettelsen, selv om tilbuddet ligner. De rettede priser bliver i prishistorikken.

### v0.8.0 – ret forkerte priser

- **Ret en pris, der ikke stemmer med avisen.** Tryk «Ret» ved et tilbud (under Tilbud eller i Ugens tur): ændr pris, mængde, førpris, enhedspris, datoer eller betingelse, eller vælg «Skjul tilbuddet». Appen viser, hvad Tjek sagde, og regner enhedspris med live.
- **Rettelsen overskrives ikke.** Den gemmes for sig og lægges oven på data, hver gang tilbuddet hentes igen. Hvis samme fejl udgives påny med nyt id (samme butik, tekst og oprindelige pris), rettes den også, når «Rettelsen gentages» er markeret.
- **Overblik og fortryd.** Kortet «Rettelser og skjulte tilbud» nederst under Tilbud lister alle rettelser med Rediger og Fortryd; Fortryd gendanner Tjeks oprindelige tal.
- Rettelser følger med i eksport/import af opsætningen og tæller med i fejlrapporten.

### v0.7.1

- Butiksopslaget prøver tre offentlige Overpass-spejle (to forsøg hver) i stedet for kun ét, så en overbelastet server (HTTP 502/504) ikke stopper opslaget. Fremdriftsdialogen viser, hvilken server der prøves.
- Rettet: linjen «Beregner fra: …» øverst var gennemsigtig og lå oven på indholdet, når man scrollede.
