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
