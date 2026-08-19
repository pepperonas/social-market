# Bug-Befund & Fix-Plan

**Stand:** 2026-08-19 · **Basis:** Commit `4feb033` · **Prüfumfang:** ~10.700 Zeilen Python (app/ + tests/)

---

## ✅ Umsetzungsstand (2026-08-19)

**Alles unten Beschriebene ist umgesetzt.** Ergebnis: **100 Tests grün** (vorher
0 lauffähig), **flake8 sauber** (vorher 531 Verstöße), bandit sauber.

| Punkt | Status | Nachweis |
|---|---|---|
| 1 Redis-Passwort im Code | ✅ rotiert + Klartext raus | kein Treffer mehr im Arbeitsbaum |
| 2 2FA ohne Verifikation | ✅ Enrolment getrennt | `test_two_factor.py::TestEnrolment` |
| 3 `is_active`-Bypass via 2FA | ✅ vor der 2FA-Weiche + in `verify_2fa` | `TestInactiveAccountCannotUse2FA` |
| 4–7 Testsuite (4 Schichten) | ✅ alle vier behoben | 100 Tests laufen |
| 8 CI verschweigt Funde | ✅ `\|\| true` raus, Lint sauber, `.flake8` | `.github/workflows/ci.yml` |
| 9 Überverkauf | ✅ `record_sale(quantity)` | `TestStockAccounting` |
| 10 Passwort-Policy tot | ✅ `validate_policy()` erzwungen | `TestPasswordPolicy` |
| 11 Open Redirect | ✅ Backslash + protokollrelativ | `TestOpenRedirect` |
| 12 TOTP-Replay | ✅ Zähler persistiert | `TestTotpReplay` + Migration |
| 13 Config nie angewandt | ✅ `APP_CONFIG` (opt-in) | siehe Hinweis unten |
| P3 | ✅ alle | `.env.example`, `LOG_FILE`, `__all__`, bare `except`, Doku |

**Jeder neue Test wurde mutiert** (Bug wieder eingebaut) und schlug nachweislich an.

⚠️ **Bewusst NICHT geändert:** der Container startet weiterhin ohne `APP_CONFIG`,
also mit der Basis-Config. `ProductionConfig` schaltet zusätzlich
`WTF_CSRF_SSL_STRICT=True`, was durchgehendes HTTPS voraussetzt — auf dem
HTTP-Trainingsaufbau (`:8080`) würde das Formulare brechen. Das ist ein
Betriebs-Entscheid, kein Codefehler; Umschalten per `APP_CONFIG=production`.

⚠️ **Offen:** Das alte Redis-Passwort steht weiterhin in der git-Historie
(Commit `018e8f3`). Die Rotation entwertet es; ein History-Rewrite wurde nicht
durchgeführt. Ebenso offen: CVE-Stand der auf Ende 2023 gepinnten
Abhängigkeiten — die CI meldet ihn jetzt, verifiziert ist er noch nicht.

---

Methodik: Testsuite ausgeführt, Config-/Boot-Kette schrittweise repariert um verdeckte Folgefehler
freizulegen (Änderungen danach vollständig zurückgenommen — Arbeitsbaum unverändert), CI-Jobs
lokal nachgestellt, Autorisierungspfade und Geschäftslogik gelesen.

---

## Kernbefund

Die Testsuite läuft **nicht** — 72 von 72 Tests brechen beim Setup ab, 0 laufen durch.
Dahinter liegen **vier gestapelte Defekte**: jeder wird erst sichtbar, wenn der davor
behoben ist. Damit ist auch der CI-Test-Job seit seiner Einführung bei jedem Push rot,
ebenso der Lint-Job (531 Verstöße). Die Tests haben also nie geschützt.

Das ist der Grund, warum die Logikfehler unten unentdeckt blieben.

---

## P0 — Sofort

### 1. Aktives Redis-Passwort hartcodiert im Quelltext
`app/__init__.py:30` — der Default für `storage_uri` enthält das **echte, aktuell in `.env`
verwendete** Redis-Passwort im Klartext. Getrackt in git seit Commit `018e8f3`
("Harden app, fix bugs…"), liegt also in der Historie und in jedem Klon.

Repo ist privat (GitHub 404) — kein öffentlicher Leak, aber:
- **Fix:** Passwort **rotieren** (in `.env`, Redis, docker-compose). Default im Code auf
  `redis://redis:6379/1` ohne Credentials ändern; fehlende Env-Var soll laut scheitern.
- Historie: `git filter-repo`/BFG nur sinnvoll, wenn nach der Rotation noch nötig — Rotation
  ist der eigentliche Fix.
- Danach: Secret-Scanner in CI (gitleaks) gegen Wiederholung.

### 2. 2FA wird ohne Verifikation scharfgeschaltet — Aussperr-Risiko
`app/routes/auth.py:325-331` + `app/models/user.py:211-222`

`enable_two_factor()` setzt `two_factor_enabled = True` **und committet** — aufgerufen wird es
aber schon beim **GET**, beim Rendern des QR-Codes. Der Guard `if current_user.two_factor_enabled:
redirect` steht davor. Folge:

- Wer die Seite nur öffnet und wieder verlässt, hat 2FA aktiv — mit einem Secret, das er
  nie gespeichert hat → **dauerhafte Aussperrung beim nächsten Login**.
- Der POST-Zweig, der den Code prüfen soll, ist dadurch **unerreichbarer toter Code**:
  der Guard fängt ihn ab und meldet „2FA is already enabled".

**Fix:** Secret beim GET nur *generieren* (in Session/DB als „pending"), `two_factor_enabled`
erst im POST nach erfolgreicher `verify_totp` setzen. Guard so umbauen, dass er den POST nicht
abfängt. Recovery-Codes ergänzen.

### 3. Deaktivierte Konten können sich per 2FA anmelden
`app/routes/auth.py:59-70` prüft `two_factor_enabled` **vor** `is_active`; `verify_2fa()`
(Zeile 113 ff.) prüft `is_active` und `is_account_locked()` **gar nicht**.

Ein gesperrter/deaktivierter Nutzer mit aktivem 2FA wird nach `verify_2fa` umgeleitet und dort
vollständig eingeloggt. **Der Sperrmechanismus ist umgehbar.**

**Fix:** `is_active` + `is_account_locked()` vor der 2FA-Weiche prüfen **und** in `verify_2fa`
erneut (Session kann zwischen den Schritten veralten). Pending-2FA-Session mit Ablaufzeit (~5 min).

---

## P1 — Testsuite & CI reparieren

Die vier Schichten, in dieser Reihenfolge (jede legt die nächste frei):

| # | Datei | Defekt | Fix |
|---|-------|--------|-----|
| 4 | `app/__init__.py:53` | `from_object(f'app.config.{config_name}')` sucht Attribut `testing` — es gibt aber `TestingConfig` + das `config`-Dict (`config.py:238`). `ImportStringError`. | `from app.config import config` und `config[config_name]` verwenden |
| 5 | `app/config.py:230` | `TestingConfig` erbt `SQLALCHEMY_ENGINE_OPTIONS` mit `pool_size`/`max_overflow`/`sslmode` → SQLite lehnt ab (`TypeError`) | `SQLALCHEMY_ENGINE_OPTIONS = {}` in `TestingConfig` |
| 6 | `app/__init__.py:206` | Logging schreibt hart nach `/var/log/marketplace/app.log` ohne Guard → `FileNotFoundError` außerhalb Docker | auf `TESTING` prüfen, Verzeichnis anlegen bzw. `OSError` auf StreamHandler zurückfallen |
| 7 | `app/models/user.py` (`last_login_ip`) | PostgreSQL-`INET` ist auf SQLite nicht kompilierbar (`UnsupportedCompilationError`). Der conftest-Kommentar „handled by SQLAlchemy's dialect adaptation" ist **falsch** | s. u. |

**Zu 7 — Grundsatzentscheidung.** Die SQLite-Teststrategie kollidiert mit dem Datenmodell
(PG-`UUID`, `INET`, `LargeBinary`+pgcrypto, Stored Procedures). Zwei Wege:

- **(a) empfohlen:** Tests gegen echtes PostgreSQL. CI stellt Postgres 15 + Redis **bereits
  bereit** und setzt `DATABASE_URL` — nur `conftest.py` verdrahtet stur `sqlite:///:memory:`.
  Änderung: `DATABASE_URL` bevorzugen, sonst SQLite. Damit greifen auch die Stored Procedures
  und die Typen entsprechen der Produktion.
- (b) `with_variant`-Typdekoratoren für INET/UUID — hält Tests dependency-frei, testet aber
  dauerhaft an anderen Typen als produktiv.

**Danach:** Suite tatsächlich grün bekommen. Erst dann ist bezifferbar, wie viele der 72 Tests
inhaltlich fehlschlagen — das ist bisher unbekannt, weil keiner je lief.

### 8. CI meldet nicht, was sie prüft
- Lint-Job: **531 flake8-Verstöße** → rot bei jedem Push. Davon ~410 kosmetisch (W293/W291),
  aber **19×F401** (ungenutzte Importe), **7×F841** (tote Variablen) sind echt.
  `E712` (`== False`) ist bei SQLAlchemy-Filtern ein Fehlalarm → gezielt ignorieren.
- Security-Job: `pip-audit … || true` — **verschluckt jeden Fund**. `|| true` entfernen.
- Abhängigkeiten sind auf Stände von Ende 2023 gepinnt (Flask 3.0.0, cryptography 41.0.7,
  Pillow 10.1.0, requests 2.31.0, urllib3 2.1.0). CVE-Status **unbestätigt** (pip-audit lokal
  nicht auflösbar, kein `pg_config`) — nach Entfernen des `|| true` in CI verifizieren und
  aktualisieren.

---

## P2 — Geschäftslogik

### 9. Lagerbestand: Überverkauf möglich
`app/models/product.py:110-114` — `record_sale()` zieht **genau 1** ab, unabhängig von
`order.quantity`. Bestellung über 10 Stück reduziert den Bestand um 1. `sales` zählt
Bestellungen statt Einheiten.

Zusätzlich: Abzug passiert erst in `_handle_paid` (`order.py:185`), nicht bei Bestellanlage.
Zwischen Anlage und Zahlung ist der Bestand ungeschützt; `validate_items()` prüft nur lesend,
ohne Sperre → **nebenläufige Checkouts verkaufen dieselbe Ware mehrfach**.

**Fix:** `record_sale(quantity)` mit Menge; Bestand bei Bestellanlage reservieren; Zeile per
`SELECT … FOR UPDATE` sperren; DB-Constraint `quantity >= 0` als letzte Verteidigung.

### 10. Passwort-Policy ist konfiguriert, greift aber nie
`config.py:81-86` definiert `PASSWORD_MIN_LENGTH=12` + Groß-/Klein-/Ziffer-/Sonderzeichen.
`User.set_password` (`user.py:129`) prüft ausschließlich `len(password) < 8`. Kein einziges
Policy-Flag wird gelesen — der Kommentar sagt es offen („only check minimum length").

**Fix:** Policy-Prüfung in `password_service` zentral implementieren und aus `set_password`
aufrufen; Registrierung/Passwortwechsel geben die verletzte Regel konkret zurück.

### 11. Open Redirect über Backslash
`auth.py:616-635` — `_is_safe_url` lässt jeden Pfad ohne `netloc` durch. `urlparse('/\evil.com')`
liefert `netloc=''`, mehrere Browser normalisieren `\` aber zu `/` → externes Ziel.

**Fix:** Backslashes vor der Prüfung ablehnen/normalisieren; nur Ziele mit führendem einzelnen
`/` erlauben (`//` und `/\` verwerfen).

### 12. TOTP ohne Replay-Schutz
`user.py:237-251` — `valid_window=1` (±30 s), aber der verbrauchte Zähler wird nicht gespeichert.
Ein abgefangener Code ist im Fenster wiederverwendbar. `verify_2fa` kennt zudem keine
Fehlversuchszählung (nur 5/min pro IP).

**Fix:** `two_factor_last_counter` persistieren und Codes `<=` dem letzten verworfen;
Fehlversuche auf das Konto zählen.

### 13. Nur die Basis-Config wird je geladen
`Dockerfile:64` startet `create_app()` **ohne Argument** → `ProductionConfig`
(`SESSION_COOKIE_SECURE`, `WTF_CSRF_SSL_STRICT=True`) wird nie angewandt. Wirkung derzeit
gering, weil die Basis-Config env-getrieben ist — aber `WTF_CSRF_SSL_STRICT` bleibt dauerhaft
`False`.

**Fix:** `create_app(os.getenv('FLASK_ENV', 'production'))` (nach Fix #4).

---

## P3 — Kleinigkeiten

- **`.env.example:29,40`** nutzt verschachtelte `${POSTGRES_PASSWORD}` — docker-compose expandiert
  das nicht (in `CLAUDE.md` als Gotcha dokumentiert). Wer SETUP.md folgt, bekommt eine kaputte
  `DATABASE_URL`. Literale Platzhalter eintragen.
- **CSP** (`__init__.py:252`): `style-src` mit `'unsafe-inline'` + jsdelivr-CDN. Für eine
  Security-Demo unschön — Bootstrap vendorn, Inline-Styles per Nonce.
- **`password_service.py:171,229`**: `except (InvalidHash, Exception)` bzw.
  `except (IndexError, ValueError, Exception)` — das breite `Exception` verschluckt alles,
  die spezifischen Typen sind wirkungslos.
- **`routes/__init__.py`**: `__all__` kennt `cart_bp`, `account_bp`, `notifications_bp` nicht
  (Registrierung läuft direkt über `register_blueprints`, also folgenlos — aber irreführend).
- **`messages.py:336`**: `get_or_404` auf ungeprüfter `message_id` aus JSON → bei fehlerhafter
  UUID DataError/500 statt 404.

---

## Reihenfolge

1. **P0 #1** (Secret rotieren) — unabhängig, sofort.
2. **P1 #4–#7** (Suite lauffähig machen) — **vor** allen Logik-Fixes, sonst arbeitet man
   weiter ohne Netz. Ergebnis: belastbare Aussage, wie viele Tests inhaltlich rot sind.
3. **P0 #2, #3** (2FA) — mit Regressionstests, die den Aussperr- und den `is_active`-Pfad pinnen.
4. **P1 #8** (CI ehrlich machen: `|| true` raus, Lint aufräumen).
5. **P2 #9–#13**, je mit Test.
6. **P3** nebenbei.

**Nicht gefunden** (explizit geprüft, unauffällig): IDOR in vendor/buyer/messages/cart — die
Ownership-Checks sind durchgängig vorhanden, inklusive der verschachtelten Route
`product/<id>/delete-image/<id>`. Upload-Validierung (`secure_filename`, Whitelist, PIL-Verify,
MIME-, Größen- und Dimensionsprüfung) ist solide. `.env`/`.env.bak` sind korrekt **nicht**
getrackt. Rollen-Decorators sind korrekt.
