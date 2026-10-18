# Testprotokoll 18.10.2026

- Python 3.13.5: `python -m pytest -q` — **8 av 8 bestått**.
- Chromium/Playwright smoke-test med lokal `/usr/bin/chromium` — **bestått**.
- Referansedata fra syntetisk test: 15 oppførte hester, 14 aktive, strøket #2 Lesja Loke, 75 historiske startoppføringer — **bestått, men IKKE hentet live**.
- Kritisk parserfeil funnet og rettet: tidligere historikk-kolonner mistet tabulatorseparatorene. Tabulatorer bevares nå, og manglende celler gir ikke forskjøvede odds/prisfelt. To nye regresjonstester er lagt til.
- Ekte innsamlingstest av Varig Orkla løp 6 med Playwright/Chromium: DNS-oppslag mot `www.rikstoto.no` feilet (`getaddrinfo EAI_AGAIN`). `robots.txt` var ikke tilgjengelig og streng policy blokkerte innsamling. **0 ekte løp hentet**.
- Feilhåndtering forbedret: lager nå `program.json`, `program.sqlite`, `program.xlsx` og `program.pdf` med eksplisitt `REVIEW_REQUIRED` også når robots-tilgang ikke kan bekreftes. Filintegritet kontrollert lokalt.
- GitHub Actions: **ikke bekreftet kjørt**; lokal testkjøring er verifisert.

**Akseptstatus: IKKE PRODUKSJONSGODKJENT.** Live-miljø med dokumentert adgang, verifisert alle løp på dagen, hestehistorikk og offisielle PDF-kilder gjenstår.

Dette er en testprotokoll, ikke en garanti for at Rikstotos dynamiske nettsted støttes på alle løpsdager.
