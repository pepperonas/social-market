# Verbesserungsplan nach Runde 3 (Stand 2026-11-08)

> Lehrumgebung (celox.io Security-Training). Blue Team; jede Maßnahme dient der
> Verteidigung oder der Lehrbarkeit.

Runde 3 ([REVIEW-2026-11.md](REVIEW-2026-11.md)) hat den Bestellfluss durchgängig benutzbar
gemacht, die Hintergrundjobs zum Laufen gebracht und die Produktionskonfiguration live
geschaltet. Dieser Plan sammelt, was danach noch fehlt. Er ist nach Wirkung sortiert:
zuerst offene Sicherheitsschulden, dann Lücken zwischen Behauptung und Wirklichkeit, dann
Testqualität, zuletzt Ausbau des Lehrstoffs.

Jeder Schritt folgt der Hausregel: Fehler beheben, die Erklärung stehen lassen, jeden neuen
Test einmal scheitern sehen.


## A — Offene Sicherheitsschulden (Entscheidung nötig)

| # | Punkt | Vorschlag | Aufwand |
|---|---|---|---|
| A1 | ✅ 2026-11-08 — `two_factor_secret` im Klartext | Eigener `TOTP_ENCRYPTION_KEY` (Fernet, über `CryptoService`), Spalte `two_factor_secret_enc LargeBinary`, SQL-Migration mit Übergangsphase: lesen aus beiden, schreiben nur verschlüsselt, danach Klartextspalte leeren. Rotation über `MultiFernet`, unabhängig von `SECRET_KEY`. Produktionswächter: ohne Schlüssel startet die App nicht. | mittel |
| A2 | ✅ 2026-11-08 — `ADMIN_PASSWORD` zusätzlich in der Live-`.env` | Zeile entfernen; die einzige Quelle bleibt `/root/.socialmarket-adminpw`. Vorher prüfen, dass Datei und Hash zusammenpassen (0600-Prüfdatei, danach `shred`). | klein |
| A3 | ✅ 2026-11-08, Rotation in `deploy.sh` ebenfalls — Deploy-Sicherungen in `/root` | Die zwei DB-Dumps (0644) zuerst löschen, danach Code-Sicherungen und `.env`-Kopie. Künftig legt `deploy.sh` Sicherungen mit 0700/0600 an und behält nur die letzten zwei. | klein |
| A4 | ✅ 2026-11-08, alle Werte tot — Altes Redis-Passwort in der git-Historie ([BUGFIX-PLAN.md](BUGFIX-PLAN.md)) | Prüfen, ob das Passwort noch irgendwo gilt; falls ja rotieren. Die Historie bewusst **nicht** umschreiben (Lehrstoff), den Fund aber als erledigt markieren, sobald der Wert tot ist. | klein |


## B — Behauptung und Wirklichkeit angleichen

Runde 3 hat mehrfach Funktionen gefunden, die beschrieben, aber nicht verdrahtet waren.
Diese Punkte sind von derselben Art.

| # | Punkt | Vorschlag | Aufwand |
|---|---|---|---|
| B1 | ✅ 2026-11-08 — Produktfreigabe existiert nur als Spalte: `vendor.py` setzt `is_approved=True` selbst, eine Admin-Freigabe gibt es nicht | Entweder echte Freigabe-Queue im Admin (Liste, Freigeben/Ablehnen mit Begründung, Audit-Eintrag) oder Spalte und Kommentare ehrlich als „Auto-Freigabe in der Lehrumgebung“ dokumentieren. Empfehlung: Queue bauen, weil sie die Rollentrennung zeigt. | mittel |
| B2 | ✅ 2026-11-08 — Bewertungen ebenso automatisch freigegeben (`buyer.py`) | Gleiche Entscheidung wie B1; mit B1 zusammen umsetzen. | klein |
| B3 | Canary-Tokens und Honeypots: Referenzcode ohne Aufrufer | Einen Honeypot wirklich anschließen (z. B. versteckte Login-Route `/admin.php` → `security_event` + optionale IP-Sperre), mit Test. Oder die Klassen in ein `examples/`-Modul verschieben. | mittel |
| B4 | ✅ 2026-11-08 — `Escrow.mark_disputed()` schreibt keinen eigenen Audit-Eintrag (bedingtes UPDATE umgeht den Listener) | Audit-Aufruf explizit im Service, wie bei den anderen Zustandswechseln. | klein |
| B5 | ✅ 2026-11-08 — Erstattung aus `paid` bucht das Lager nicht zurück | Admin-Entscheidung im Formular abfragen („Ware nie versandt → Lager zurückbuchen“), statt sie stillschweigend offenzulassen. | klein |
| B6 | Gast-Warenkorb in `cart.py` angekündigt, aber nicht vorhanden | Kommentar entfernen; der Marktplatz ist bewusst nur mit Login erreichbar. | klein |
| B7 | ✅ 2026-11-08 (Liste gab es schon; Vorschläge neu) — IP-Sperren nur per Formular; keine Liste der aktiven Sperren mit Ablauf | Übersicht im Admin-Sicherheitsbereich, Ablaufdatum, wer gesperrt hat. Optional: der Security-Scan-Job schlägt Sperren vor (nie automatisch). | klein |


## C — Testqualität

| # | Punkt | Vorschlag | Aufwand |
|---|---|---|---|
| C1 | ✅ 2026-11-08 — CI startet PostgreSQL und Redis, die Suite läuft aber trotzdem auf SQLite | Zweiter Testlauf gegen den PG-Dienst (`TEST_DATABASE_URL`), mindestens für Bestellfluss, Jobs, Audit-Prozeduren und Zeitzonen. Genau die Fehlerklasse, die SQLite in Runde 3 verdeckt hat (Rollback, NaN, `TIMESTAMPTZ`, negativer OFFSET). | mittel |
| C2 | ✅ 2026-11-08 — Nebenläufigkeit nur über künstlich veraltete Objekte getestet | Zwei echte Verbindungen gegen PG: doppelte Zahlung, gleichzeitige Lagerreservierung, Rennen zwischen Stornierung und Versand. | mittel |
| C3 | Routen-Coverage `admin.py` 61 %, `vendor.py` 63 % | Verhaltenstests über HTTP für Admin-Nutzerverwaltung, Streitfall-Entscheidung und Vendor-Produktbearbeitung. Ziel: CI-Schwelle für Routen von 70 auf 75 % anheben. | mittel |
| C4 | Keine Branch-Coverage | `--cov-branch` messen und berichten; vorerst ohne Schwelle. | klein |
| C5 | Kein Browser-Test | Ein Playwright-Rauchtest gegen die Docker-Umgebung: Registrieren → Produkt → Bestellen → Bezahlen → Versand → Abschluss, plus CSP-Verstöße in der Konsole als Fehler. Hätte K1 aus Runde 3 sofort gezeigt. | mittel |
| C6 | Mutationsproben laufen von Hand | `mutmut` für `services/` und `models/order.py` als nächtlicher, nicht blockierender Job. | klein |


## D — Betrieb

| # | Punkt | Vorschlag | Aufwand |
|---|---|---|---|
| D1 | ✅ 2026-11-08 — Log-Rechte wurden erst beim Deploy auffällig (`app.log` gehörte root) | `deploy.sh` prüft Eigentümer und Modus von Log- und Upload-Verzeichnis vor dem Neustart und bricht sonst ab. | klein |
| D2 | ✅ 2026-11-08 (Drop-in auf dem Server) — Kein Hinweis, wenn ein Job-Timer scheitert | `OnFailure=` an den beiden Job-Units, wie bei den homestack-Sicherungen. | klein |
| D3 | Teilweise: nächtlicher Dump `/var/backups/postgres/socialmarket-*.dump` existiert — Sicherung der Live-DB | Prüfen, ob `socialmarket` in `vps-data-backup.sh` erfasst ist; Rückspielprobe in eine Wegwerf-DB. | klein |
| D4 | `/admin/system-health` | Job-Läufe (letzter Erfolg je Timer), DB-Größe, Redis-Erreichbarkeit anzeigen statt nur statischer Werte. | klein |


## E — Lehrstoff und Benutzbarkeit

| # | Punkt | Vorschlag | Aufwand |
|---|---|---|---|
| E1 | Die Lehrinhalte stecken in Markdown-Dateien im Repo | Eine Seite „Wie diese Seite dich schützt“ im Profil: zeigt für den eingeloggten Nutzer die tatsächlich wirksamen Maßnahmen (Argon2id-Parameter, Sitzungsversion, 2FA-Status, letzte Logins aus `auth_log`), mit Verweis auf die Doku. | mittel |
| E2 | Fehlerkatalog der drei Runden | Ein kompaktes Kapitel „Was hier kaputt war“ mit je einem Absatz pro Fund, Ursache und Test, als Einstieg für Kursteilnehmende. | klein |
| E3 | PGP-Nachrichten: Schlüssel liegen serverseitig | Klar ausweisen, dass serverseitiges Entschlüsseln kein Ende-zu-Ende ist; optional clientseitiges Entschlüsseln mit OpenPGP.js als Vergleichsvariante. | groß |
| E4 | Barrierefreiheit und Kontrast | Einmal vollständig messen (Kontrast, Fokusreihenfolge, Formular-Labels), wie in den anderen celox-Projekten. | klein |


## Vorgeschlagene Reihenfolge

| Schritt | Inhalt | Begründung |
|---|---|---|
| 1 | ✅ A2, A3, A4, D1, D2 (2026-11-08) | Kleine Betriebsschulden, sofort erledigt, wenig Risiko |
| 2 | ✅ A1 (2026-11-08) | Größte verbleibende Sicherheitsschuld |
| 3 | ✅ C1, C2 (2026-11-08) | Bevor weitere Logik dazukommt, die Fehlerklasse „nur PostgreSQL“ abdecken |
| 4 | ✅ B1, B2, B4, B5, B7 (2026-11-08) | Behauptungen einlösen; jeder Punkt bekommt einen HTTP-Test |
| 5 | B3, B6 | Referenzcode anschließen oder ehrlich auslagern |
| 6 | C3, C4, C5, C6 | Testabdeckung und Browser-Rauchtest |
| 7 | D3, D4, E1–E4 | Betrieb abrunden, Lehrstoff ausbauen |

**Entschieden und umgesetzt (2026-11-08):** Der TOTP-Schlüssel ist eine eigene Variable in
der `.env` (`TOTP_ENCRYPTION_KEY`), die Migration ist verlustfrei mit Übergangsphase. Details
im [Review-Nachtrag](REVIEW-2026-11.md#nachtrag-2026-11-08-totp-geheimnisse-verschlüsselt-a1).
