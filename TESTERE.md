# Tilbudsagent – til testere (Windows 11 og Android)

Tilbudsagent samler ugens tilbud fra Tjek, holder styr på priser og viser, hvilke butikker der er værd at køre til, når kørslen er regnet med.

## Kom i gang
1. Hent `Tilbudsagent.exe` fra **Releases** her på GitHub (seneste version). Der ligger også en `.sha256`-fil, hvis du vil kontrollere downloaden.
2. Dobbeltklik på filen. Windows viser sandsynligvis **«Windows har beskyttet din pc»** (SmartScreen), fordi programmet ikke er digitalt signeret. Vælg **Flere oplysninger → Kør alligevel**.
3. Din browser åbner Tilbudsagent. Første gang tager det et par sekunder.
4. Gå til **Indstillinger**: skriv din adresse (søg og vælg den), ret butikker og afstande, og tryk **Gem**.
5. Tryk **Hent tilbud**. Det tager typisk et par minutter. Lad siden stå åben.
6. Under **Varer** tilføjer og retter du dine egne varer. Vælg om du vil have alle mærker eller kun et bestemt produkt, og udfyld din normalpris, så bliver rabatterne præcise.

Luk programmet med knappen **Afslut** øverst til højre. Starter du det igen, mens det kører, åbner det bare den eksisterende.

## Android
1. Åbn **Releases** på GitHub i telefonens browser og hent `Tilbudsagent.apk` (seneste version).
2. Åbn filen. Android spørger, om din browser må installere ukendte apps: tillad det (**Indstillinger → Tillad fra denne kilde**). Det er normalt for apps uden for Play Store.
3. Åbn **Tilbudsagent**. Første start tager et par sekunder. Brugerfladen er den samme som på pc.
4. Under **Indstillinger** skriver du din hjemmeadresse. Er du et andet sted, bruger du **Jeg er et andet sted → Brug min GPS-position**.
5. Opdatering: hent den nyeste `.apk` og åbn den; dine data bevares. Vil du have automatisk opdatering, kan du bruge den gratis app **Obtainium** og pege den på `https://github.com/Pwrtzner/tilbudsagent`.
6. Flyt data mellem pc og telefon med **Indstillinger → Sikkerhedskopi og flytning** (eksport gemmes i mappen `Download/Tilbudsagent`).

## Dine data
Gemmes på din egen pc i `%APPDATA%\Tilbudsagent` (databasen `priser.db` og en logfil). Intet sendes nogen steder, bortset fra:
- opslag af tilbud hos Tjek (med dit lokationsområde),
- adresseopslag hos OpenStreetMap, når du søger efter din adresse.

Appen gemmer alle tilbud, den ser, så prishistorikken vokser over tid, og den henter selv nye tilbud, når der er gået over et døgn, mens den er åben (kan slås fra under Indstillinger).

Under **Indstillinger → Sikkerhedskopi og flytning** kan du eksportere og importere din opsætning (varer, butikker, adresse, regler) til en anden pc. «Eksportér komplet» tager også historikken med.

## Fejl og feedback
Tryk **Indstillinger → Gem fejlrapport** og send filen til den, der gav dig appen. Den indeholder version, system, varer og seneste log, men ikke din adresse.

Skriv gerne også: hvad forventede du, hvad skete der, og hvilken butik/vare det gælder.

## Kendte begrænsninger
- Tjeks tilbuds-API er udokumenteret og kan ændre sig. Hvis hentning pludselig fejler for alle, er det sandsynligvis dét.
- Tilbudspriser er kampagnepriser; hyldeprisen kender programmet ikke. Udfyld derfor normalpris på dine varer.
- Pakkestørrelser kan mangle i tilbuddene. Så vises enhedsprisen som «ukendt», og tilbuddet tæller ikke med i turen.
