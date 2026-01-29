# Encrypted Messaging System

## Overview

Social Market implements a **mandatory end-to-end encrypted messaging system** using PGP encryption. All messages MUST be encrypted - plaintext messages are blocked at the application level.

## Key Features

✅ **Mandatory Encryption** - No plaintext messages allowed
✅ **PGP/OpenPGP Standard** - Industry-standard encryption
✅ **Two Encryption Modes** - Auto-encrypt or manual pre-encrypted messages
✅ **Flexible Communication** - Admin ↔ Users, Vendor ↔ Buyers
✅ **Auto-Deletion** - Messages expire after 30 days (OPSEC)
✅ **Zero-Knowledge** - Messages stored encrypted, server cannot decrypt
✅ **Rate Limited** - Prevents spam and abuse

## Who Can Message Whom

### Communication Matrix

| From/To | Buyer | Vendor | Admin |
|---------|-------|--------|-------|
| **Buyer** | ❌ | ✅ | ✅ |
| **Vendor** | ✅ | ❌ | ✅ |
| **Admin** | ✅ | ✅ | ✅ |

### Access Control

- **Admin**: Can message any user (support/moderation)
- **Vendors**: Can message buyers (customer service) and admins
- **Buyers**: Can message vendors (inquiries) and admins (support)
- **Self-messaging**: Blocked (cannot message yourself)

## Encryption Modes

### 1. Auto-Encrypt Mode (Recommended)

**How it works:**
1. User writes message in plaintext
2. System automatically encrypts with recipient's PGP public key
3. Encrypted message stored in database
4. Only recipient can decrypt with their private key

**Requirements:**
- Recipient must have uploaded their PGP public key
- If no public key exists, auto-encryption fails

**User Experience:**
```
User: "Hello, I have a question about your product"
  ↓ [System encrypts with recipient's public key]
Database: "-----BEGIN PGP MESSAGE----- ... -----END PGP MESSAGE-----"
```

### 2. Manual Mode (Advanced)

**How it works:**
1. User encrypts message externally (e.g., GPG command line)
2. Pastes pre-encrypted PGP message into form
3. System validates PGP format
4. Encrypted message stored as-is in database

**Requirements:**
- Message must be valid PGP format
- Must start with `-----BEGIN PGP MESSAGE-----`
- Must end with `-----END PGP MESSAGE-----`

**Use Cases:**
- Recipient doesn't have PGP key on platform yet
- User prefers external encryption tools
- Air-gapped encryption workflow
- Multi-recipient encryption

**Example:**
```bash
# Encrypt message externally
echo "Secret message" | gpg --encrypt --armor --recipient vendor@example.com

# Paste result into Social Market manual mode:
-----BEGIN PGP MESSAGE-----

hQEMA...
[encrypted content]
...=xyz
-----END PGP MESSAGE-----
```

## Security Features

### 1. Encryption Enforcement

**Code-Level Protection:**
```python
# CRITICAL: Verify message is encrypted before saving
if not message.is_encrypted:
    raise ValueError('SECURITY: Attempted to send unencrypted message')

if not message.content_encrypted:
    raise ValueError('SECURITY: No encrypted content')
```

**Validation Checks:**
- Auto mode: Rejects if message already starts with PGP header
- Manual mode: Rejects if message doesn't match PGP format
- Both modes: Verify `is_encrypted=True` before database save

### 2. Zero-Knowledge Architecture

**Server Cannot Decrypt:**
- Messages encrypted with recipient's public key
- Server doesn't have recipient's private key
- Even database compromise doesn't reveal message content

**Decryption Process:**
1. User clicks "Decrypt Message"
2. Modal prompts for private key + passphrase
3. Decryption happens server-side (temporary, not stored)
4. Decrypted text displayed to user
5. Private key cleared from memory

### 3. Message Lifecycle

**Auto-Deletion (OPSEC):**
```python
expires_at = created_at + 30 days  # Configurable
```

- All messages auto-expire after 30 days (default)
- Configurable via `MESSAGE_RETENTION_DAYS` environment variable
- Automatic cleanup via background tasks

**Soft Delete:**
- User deletes message: Marked as deleted for that user only
- When both participants delete: Permanently removed from database
- Prevents accidental data loss

### 4. Rate Limiting

**Limits:**
- New thread: 10 messages/hour per user
- Reply to thread: 20 messages/hour per user
- General messages: 100 messages/hour per user

**Purpose:**
- Prevent spam
- Mitigate DoS attacks
- Encourage thoughtful communication

## User Interface

### Inbox View

**Features:**
- List of all conversations
- Unread message badge (⚠️ warnings)
- Participant role badge (Admin/Vendor/Buyer)
- Last message timestamp
- Encryption status (🔒)

**Admin-Specific:**
- "Message User" button
- Access to all users list

### Thread View

**Message Display:**
- Sender identification (You / Username)
- Timestamp
- Encrypted content preview (first 100 chars)
- Decrypt button (for recipients only)
- Delete button (soft delete)

**Send Message Form:**
- Encryption mode selector (Auto / Manual)
- Contextual help text
- Warning if recipient has no PGP key
- Character counter (max 10,000)

### Decryption Modal

**User Provides:**
1. PGP private key (paste full key block)
2. Passphrase (if key is password-protected)

**AJAX Decryption:**
- POST to `/messages/decrypt`
- Server decrypts temporarily
- Returns plaintext to browser
- Server clears private key from memory

**Security:**
- Private key transmitted over HTTPS
- Not stored in database or logs
- Cleared from memory after decryption
- User responsible for key security

## Database Schema

### MessageThread

```sql
CREATE TABLE message_threads (
    id UUID PRIMARY KEY,

    -- Flexible participants (any two users)
    participant_1_id UUID NOT NULL REFERENCES users(id),
    participant_2_id UUID NOT NULL REFERENCES users(id),

    -- Legacy fields (backwards compatibility)
    buyer_id UUID REFERENCES users(id),
    vendor_id UUID REFERENCES users(id),

    -- Optional order association
    order_id UUID REFERENCES orders(id),

    -- Metadata
    subject VARCHAR(200),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_message_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraint: Participants must be different
    CONSTRAINT chk_different_participants
        CHECK (participant_1_id != participant_2_id)
);
```

### Message

```sql
CREATE TABLE messages (
    id UUID PRIMARY KEY,
    thread_id UUID NOT NULL REFERENCES message_threads(id),

    -- Participants
    sender_id UUID NOT NULL REFERENCES users(id),
    recipient_id UUID NOT NULL REFERENCES users(id),

    -- ENCRYPTED CONTENT (PGP)
    content_encrypted BYTEA NOT NULL,  -- PGP-encrypted message
    is_encrypted BOOLEAN DEFAULT TRUE,

    -- Metadata (NOT encrypted)
    has_attachment BOOLEAN DEFAULT FALSE,
    attachment_filename VARCHAR(255),

    -- Read status
    is_read BOOLEAN DEFAULT FALSE,
    read_at TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,  -- Auto-delete after expiry

    -- Soft delete (per-user)
    is_deleted_by_sender BOOLEAN DEFAULT FALSE,
    is_deleted_by_recipient BOOLEAN DEFAULT FALSE
);
```

## API Endpoints

### GET /messages/
**Purpose:** View inbox
**Auth:** Required
**Returns:** List of threads with unread counts

### GET /messages/thread/<thread_id>
**Purpose:** View thread messages
**Auth:** Required (must be participant)
**Returns:** Thread + encrypted messages

### GET /messages/new/<recipient_id>
**Purpose:** Start new conversation
**Auth:** Required
**Returns:** New message form

### POST /messages/new/<recipient_id>
**Purpose:** Send first message in thread
**Auth:** Required
**Rate Limit:** 10/hour
**Body:**
```json
{
  "subject": "Optional subject",
  "message": "Plaintext or PGP-encrypted",
  "encryption_mode": "auto" | "manual"
}
```

### POST /messages/send/<thread_id>
**Purpose:** Reply to thread
**Auth:** Required (must be participant)
**Rate Limit:** 20/hour
**Body:**
```json
{
  "message": "Plaintext or PGP-encrypted",
  "encryption_mode": "auto" | "manual"
}
```

### POST /messages/decrypt
**Purpose:** Decrypt message (AJAX)
**Auth:** Required (must be recipient)
**Body:**
```json
{
  "message_id": "uuid",
  "private_key": "-----BEGIN PGP PRIVATE KEY BLOCK-----...",
  "passphrase": "optional-passphrase"
}
```
**Returns:**
```json
{
  "success": true,
  "decrypted_message": "Original plaintext"
}
```

### POST /messages/delete/<message_id>
**Purpose:** Delete message
**Auth:** Required (sender or recipient)
**Returns:** Redirect to thread

### GET /messages/admin/users (Admin Only)
**Purpose:** List all users for messaging
**Auth:** Admin only
**Returns:** User list with PGP key status

## Configuration

### Environment Variables

```bash
# Message retention (days)
MESSAGE_RETENTION_DAYS=30

# Max message length
MESSAGE_MAX_LENGTH=10000

# Require PGP encryption (enforced at code level)
REQUIRE_PGP_ENCRYPTION=true  # Always true, cannot be disabled
```

### Flask Config

```python
# app/config.py
class Config:
    MESSAGE_RETENTION_DAYS = int(os.environ.get('MESSAGE_RETENTION_DAYS', 30))
    MESSAGE_MAX_LENGTH = int(os.environ.get('MESSAGE_MAX_LENGTH', 10000))
    REQUIRE_PGP_ENCRYPTION = True  # Hardcoded - cannot be disabled
```

## Usage Examples

### Example 1: Buyer Messages Vendor (Auto-Encrypt)

1. Buyer browses marketplace
2. Clicks "Contact Vendor" on product page
3. Redirected to `/messages/new/<vendor_id>`
4. **Auto-encrypt mode selected** (default)
5. Buyer types: "Is this item still available?"
6. System checks: Vendor has PGP public key ✅
7. System encrypts message with vendor's key
8. Encrypted message saved to database
9. Vendor receives notification
10. Vendor views thread, clicks "Decrypt"
11. Vendor provides private key + passphrase
12. Message decrypted: "Is this item still available?"

### Example 2: Admin Messages User (Manual Mode)

1. Admin navigates to `/messages/admin/users`
2. Selects user from list
3. Redirected to `/messages/new/<user_id>`
4. **Manual mode selected**
5. Admin encrypts message externally:
   ```bash
   echo "Your account has been verified" | \
     gpg --encrypt --armor --recipient user@example.com > encrypted.txt
   ```
6. Admin pastes PGP message into form
7. System validates PGP format ✅
8. Encrypted message saved as-is
9. User decrypts with their private key

### Example 3: Vendor Replies to Buyer

1. Vendor sees unread message badge in inbox
2. Clicks thread
3. Clicks "Decrypt Message"
4. Provides private key + passphrase
5. Reads: "Is this item still available?"
6. Scrolls to reply form
7. Types: "Yes, it's in stock. Ready to ship."
8. System auto-encrypts with buyer's key
9. Buyer receives encrypted reply

## Security Best Practices

### For Users

1. **Generate Strong PGP Keys:**
   - Use RSA-4096 (recommended)
   - Strong passphrase (12+ characters)
   - Keep private key secure (never share)

2. **Key Management:**
   - Backup private key securely offline
   - Use password manager for passphrase
   - Rotate keys annually

3. **Operational Security:**
   - Don't decrypt messages on shared computers
   - Clear browser cache after reading sensitive messages
   - Use manual mode for ultra-sensitive communications

### For Administrators

1. **Monitoring:**
   - Track messages with missing PGP keys
   - Monitor rate limit violations
   - Review audit logs regularly

2. **User Education:**
   - Encourage PGP key generation
   - Provide key generation tutorials
   - Explain encryption benefits

3. **Backup:**
   - Encrypted database backups
   - Test restoration procedures
   - Document key recovery processes

## Troubleshooting

### "Recipient does not have a PGP public key"

**Cause:** Recipient hasn't generated PGP keys yet

**Solution:**
1. Ask recipient to visit `/auth/pgp-keys`
2. Generate RSA-4096 keypair
3. System auto-saves public key to profile
4. Or use manual mode with external encryption

### "Decryption failed: wrong passphrase"

**Cause:** Incorrect private key passphrase

**Solution:**
1. Verify passphrase spelling/capitalization
2. Check if using correct private key
3. Ensure key hasn't expired
4. Try decrypting externally to verify key works

### "Invalid PGP message format"

**Cause:** Manual mode message not properly formatted

**Solution:**
1. Ensure message starts with `-----BEGIN PGP MESSAGE-----`
2. Ensure message ends with `-----END PGP MESSAGE-----`
3. Include full PGP armor (no truncation)
4. Check for copy-paste errors

### "Rate limit exceeded"

**Cause:** Too many messages sent too quickly

**Solution:**
1. Wait for rate limit window to reset
2. Current limits:
   - New threads: 10/hour
   - Replies: 20/hour
3. Contact admin if legitimate use case exceeds limits

## Compliance

### GDPR

- **Right to erasure:** Soft delete + hard delete after 30 days
- **Data portability:** Export encrypted messages
- **Privacy by design:** Encryption mandatory
- **Data minimization:** Only essential metadata stored

### Security Standards

- **OWASP:** Encryption at rest and in transit
- **NIST:** OpenPGP standard (SP 800-57)
- **ISO 27001:** Access control and audit logging

## Future Enhancements

**Potential Features:**
- [ ] File attachments (encrypted)
- [ ] Message search (metadata only)
- [ ] Read receipts (opt-in)
- [ ] Group messaging (multi-recipient PGP)
- [ ] WebPGP (browser-based decryption)
- [ ] Perfect forward secrecy (OTR/Signal protocol)

---

**© 2026 Social Market - Educational Use Only**
