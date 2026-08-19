# Security Policy

## This repository is a teaching artifact

Social Market is a **blue team training environment**. It is published so that
defenders can read a complete application and its security review side by side.

That shapes how vulnerability reports are handled here.

## Known and intentional properties

The following are **documented, not accidental**. Please do not report them as
vulnerabilities — read the linked material instead, that is the point:

| Property | Where it is explained |
|---|---|
| Every credential in this repository is public | `LOGIN_CREDENTIALS.md`, README |
| Seed accounts share one well-known password | `app/cli.py`, `LOGIN_CREDENTIALS.md` |
| A real pepper once leaked through documentation | `docs/PASSWORD_SECURITY.md` (worked example) |
| IP blocking fails **open** on database errors | `tests/test_services_security.py::TestFailureMode` |
| Crypto salt for `CryptoService` is fixed | `app/services/crypto_service.py` (must be deterministic to decrypt) |
| `style-src` allows `unsafe-inline` | Bootstrap from CDN; `script-src` is nonce-gated and does not |
| Historic security findings are left visible | `docs/BUGFIX-PLAN.md` |

## What is worth reporting

- A control that is **claimed to work but does not** (the failure mode this
  project cares most about — see the audit for four real examples).
- A test that passes **for the wrong reason**, i.e. would still pass with the
  bug reintroduced. These are worse than missing tests.
- Anything that would make a *reader* learn something false.
- An actual secret that is still live in this repository.

## How to report

Open a GitHub issue. If a report contains a live secret, mark it clearly and do
not include the secret value itself.

## Deployment stance

Any hosted instance is a **read-only teaching demo with disposable data**. It is
not a production system, holds no real personal data, processes no real
payments, and its accounts are expected to be public. Do not deploy this project
internet-facing under the assumption that it is hardened for that — it is not,
and the README says so on purpose.
