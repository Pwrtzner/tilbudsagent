# Tilbudsagent – til testere (Windows 11)

Tilbudsagent samler ugens tilbud fra Tjek, holder styr på priser og viser, hvilke butikker der er værd at køre til, når kørslen er regnet med.

## Kom i gang
1. Hent `Tilbudsagent.exe` fra **Releases** her på GitHub (seneste version). Der ligger også en `.sha256`-fil, hvis du vil kontrollere downloaden.
2. Dobbeltklik på filen. Windows viser sandsynligvis **«Windows har beskyttet din pc»** (SmartScreen), fordi programmet ikke er digitalt signeret. Vælg **Flere oplysninger → Kør alligevel**.
3. Din browser åbner Tilbudsagent. Første gang tager det et par sekunder.
4. Gå til **Indstillinger**: skriv din adresse (søg og vælg den), ret butikker og afstande, og tryk **Gem**.
5. Tryk **Hent tilbud**. Det tager typisk et par minutter. Lad siden stå åben.
6. Under **Varer** tilføjer og retter du dine egne varer. Vælg om du vil have alle mærker eller kun et bestemt produkt, og udfyld din normalpris, så bliver rabatterne præcise.

Luk programmet med knappen **Afslut** øverst til højre. Starter du det igen, mens det kører, åbner det bare den eksisterende.

## Dine data
Gemmes på din egen pc i `%APPDATA%\Tilbudsagent` (databasen `priser.db` og en logfil). Intet sendes nogen steder, bortset fra:
- opslag af tilbud hos Tjek (med dit lokationsområde),
- adresseopslag hos OpenStreetMap, når du søger efter din adresse.

Under **Indstillinger → Sikkerhedskopi og flytning** kan du eksportere og importere din opsætning (varer, butikker, adresse, regler) til en anden pc.

## Fejl og feedback
Tryk **Indstillinger → Gem fejlrapport** og send filen til den, der gav dig appen. Den indeholder version, system, varer og seneste log, men ikke din adresse.

Skriv gerne også: hvad forventede du, hvad skete der, og hvilken butik/vare det gælder.

## Kendte begrænsninger
- Tjeks tilbuds-API er udokumenteret og kan ændre sig. Hvis hentning pludselig fejler for alle, er det sandsynligvis dét.
- Tilbudspriser er kampagnepriser; hyldeprisen kender programmet ikke. Udfyld derfor normalpris på dine varer.
- Pakkestørrelser kan mangle i tilbuddene. Så vises enhedsprisen som «ukendt», og tilbuddet tæller ikke med i turen.
