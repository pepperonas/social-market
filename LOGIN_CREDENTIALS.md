# Login Credentials - Social Market Training Environment

## Access URL
**http://localhost:8080/auth/login**

---

## Default Accounts

### Admin Account
- **Username:** `admin`
- **Password:** `ChangeMe123!`
- **Access:** Admin Dashboard, User Management, Security Monitoring, Audit Logs

### Buyer Accounts (10 available)
- **Usernames:** `clicky_mcclickface`, `bob_from_accounting`, `password_pete`, `sudo_susan`, `two_factor_tina`, `phishy_phil`, `cache_money`, `patch_tuesday`, `cookie_monster`, `admin_admin`
- **Why these names:** each account is a persona from awareness training. See the README for who they are.
- **Password:** `Password123!` (same for all buyers)
- **Access:** Marketplace, Orders, Messages, Profile

### Vendor Accounts (5 available)
- **Usernames:** `salt_n_peppa`, `zero_cool`, `null_bytes`, `entropy_ella`, `rubber_ducky`
- **Password:** `Password123!` (same for all vendors)
- **Access:** Vendor Dashboard, Product Management, Order Management, Messages

---

## Password Requirements

Enforced server-side by `PasswordService.validate_policy()` and configurable in `.env`:

- Minimum **12** characters
- Upper case, lower case, a digit and a symbol

The registration and PGP forms offer generated BIP-39 passphrases that satisfy
all of it — see `app/services/passphrase_service.py`. (This document previously
claimed "minimum 8 characters, no special character requirements"; the policy
existed in config but was never enforced, and the doc described the bug rather
than the intent.)

---

## Notes
- All accounts are pre-seeded for testing
- Login rate limiting: 50 requests/second (general browsing)
- Failed login attempts are logged
- Sessions expire after 1 hour of inactivity

---

## Troubleshooting

If login doesn't work:
1. Clear browser cookies
2. Try in incognito/private window
3. Check that Docker containers are running: `docker ps`
4. Restart services: `docker-compose restart`

---

**EDUCATIONAL USE ONLY - Social Market 2026**
