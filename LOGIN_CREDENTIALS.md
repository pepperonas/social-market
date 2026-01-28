# Login Credentials - Social Market Training Environment

## Access URL
**http://localhost:8080/auth/login**

---

## Default Accounts

### Admin Account
- **Username:** `admin`
- **Password:** `password123`
- **Access:** Admin Dashboard, User Management, Security Monitoring, Audit Logs

### Buyer Accounts (10 available)
- **Usernames:** `buyer1`, `buyer2`, `buyer3`, `buyer4`, `buyer5`, `buyer6`, `buyer7`, `buyer8`, `buyer9`, `buyer10`
- **Password:** `password123` (same for all buyers)
- **Access:** Marketplace, Orders, Messages, Profile

### Vendor Accounts (5 available)
- **Usernames:** `vendor1`, `vendor2`, `vendor3`, `vendor4`, `vendor5`
- **Password:** `password123` (same for all vendors)
- **Access:** Vendor Dashboard, Product Management, Order Management, Messages

---

## Password Requirements
- Minimum 8 characters
- No special character requirements (simplified for training)

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
