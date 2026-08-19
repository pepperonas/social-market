# Contributing

Contributions are welcome, with one framing that governs everything below:
**this project is read as teaching material.** A change that makes the code
marginally nicer but the lesson less clear is a net loss.

## The house rule for tests

Every test must be able to **fail for its stated reason**.

Before opening a PR that adds a test, reintroduce the bug it claims to catch and
watch it go red. A test nobody has seen fail is not an assurance — it is
decoration. Two concrete traps that have already caught contributors here:

1. **Text-matching assertions must run against comment-free source.** The docs
   in this repo quote removed code verbatim, so a naive `in source` check passes
   against the very thing it was meant to forbid.
2. **Anchors repeat.** `if tab == 'power'` occurs twice; assert on the property
   you care about, not on the first line that happens to match.

## Test style

Tests are written as arguments. Prefer:

```python
def test_deactivated_user_with_2fa_cannot_login(self, ...):
    """
    Regression: login() checked two_factor_enabled BEFORE is_active, so a
    deactivated account was redirected to verify_2fa and logged in there.
    """
```

over a bare assertion with no stated stake. Someone is going to read this to
learn what the control is for.

## Running things

```bash
pytest tests/ -v                                  # 278 tests, no Docker needed
pytest tests/ --cov=app --cov-report=term-missing # coverage
flake8 app/ tests/                                # settings live in .flake8
bandit -r app/ -ll --skip B101                    # static security lint
```

## What will be declined

- Exploit code, offensive tooling, or features whose purpose is attack rather
  than defence.
- Changes that make this look like a production-ready marketplace. It is not
  one, and pretending otherwise is the failure mode this project warns about.
- Silently rewriting a documented past mistake. The mistakes are the curriculum;
  correct them *and* leave the explanation.

## Documenting a fix

If you fix something real, say what it was in the docstring or in
`docs/BUGFIX-PLAN.md`. "Fixed bug" teaches nobody. "Order of checks: 2FA was
evaluated before is_active, so deactivation was bypassable" teaches everybody.
