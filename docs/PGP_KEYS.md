# PGP Key Generation - RSA-4096

## Overview

Social Market includes a secure PGP key generation system that allows users to create RSA-4096 keypairs directly in the web interface. This feature is designed for educational purposes to demonstrate secure key generation practices.

## Features

### Security Features

- **RSA-4096 Encryption**: Industry-standard 4096-bit RSA keys for maximum security
- **Client-Side Focus**: Keys are generated server-side but never permanently stored
- **Strong Passphrase Protection**: Private keys are encrypted with user-provided passphrases
- **Passphrase Validation**: Real-time strength checking with minimum 12-character requirement
- **Rate Limiting**: 3 key generations per hour to prevent abuse
- **Temporary Storage**: Keys stored only in session until downloaded
- **Secure Entropy**: Uses system's cryptographic random number generator
- **OpenPGP Standard**: Compatible with all standard PGP tools (GPG, Kleopatra, etc.)

### Key Generation Options

- **Key Length**: 2048, 3072, or 4096 bits (4096 recommended)
- **Expiration**: Never, 1 year, 2 years, or 5 years
- **Identity**: Full name and email address
- **Comment**: Optional key comment field

## Usage

### Accessing Key Generation

1. Log in to your account
2. Click "🔐 PGP Keys" in the navigation bar
3. Fill out the key generation form

### Generating Keys

**Required Information:**
- Full Name (min. 3 characters)
- Email Address (valid format)
- Passphrase (min. 12 characters)
- Passphrase Confirmation

**Optional Settings:**
- Key Length (default: 4096-bit)
- Expiration Period (default: never)

### Generation Process

1. Fill out the form with your information
2. Create a strong passphrase (16+ characters recommended)
3. Click "Generate RSA-4096 Keypair"
4. Wait 30-60 seconds for key generation
5. Download your keys immediately
6. Store them securely offline

### Downloading Keys

After successful generation, you can download:

- **Public Key**: Share with others for encrypted communication
- **Private Key**: Keep secret, never share
- **Both Keys**: Complete keypair in one file

## Security Best Practices

### Passphrase Guidelines

- **Minimum**: 12 characters (enforced)
- **Recommended**: 16+ characters
- **Composition**: Mix of uppercase, lowercase, numbers, and symbols
- **Avoid**: Dictionary words, common patterns, personal information
- **Storage**: Use a password manager or secure physical storage

### Key Storage

**Private Key:**
- Store offline on encrypted USB drive
- Backup to multiple secure locations
- Never store unencrypted in cloud storage
- Delete from downloads folder after importing to PGP client

**Public Key:**
- Safe to share publicly
- Upload to key servers (optional)
- Include in email signatures
- Share with communication partners

### Key Import

**GPG (Command Line):**
```bash
# Import public key
gpg --import public_key_[keyid].asc

# Import private key
gpg --import private_key_[keyid].asc

# Verify import
gpg --list-keys
gpg --list-secret-keys
```

**Kleopatra (Windows):**
1. File → Import Certificates
2. Select key files
3. Enter passphrase when prompted

**GPG Suite (macOS):**
1. Double-click key file
2. GPG Keychain will open
3. Enter passphrase to import private key

## Technical Implementation

### Backend Architecture

**Service Layer:**
- `app/services/pgp_service.py` - PGP operations using python-gnupg
- Temporary GPG home directory for isolation
- Secure key generation with configurable parameters
- Passphrase strength validation

**Routes:**
- `GET /auth/pgp-keys` - Key generation form
- `POST /auth/generate-pgp-key` - Generate keypair (rate limited)
- `GET /auth/download-keys` - Display generated keys
- `GET /auth/download-key/<type>` - Download key file
- `POST /auth/clear-generated-keys` - Clear session keys
- `POST /auth/validate-passphrase` - AJAX passphrase validation

**Rate Limiting:**
- 3 key generations per hour per user
- Prevents resource exhaustion attacks
- Enforced via Flask-Limiter

### Key Generation Algorithm

```python
def generate_keypair(name, email, passphrase, key_length=4096):
    """
    Generate RSA keypair with:
    - RSA algorithm
    - Specified key length (2048-8192 bits)
    - Passphrase-encrypted private key
    - Optional expiration date
    - OpenPGP format
    """
```

### Security Validations

**Input Validation:**
- Name: minimum 3 characters
- Email: valid email format
- Passphrase: minimum 12 characters, strength check
- Key length: 2048-8192 bits (max for DoS prevention)

**Passphrase Strength Scoring:**
- Length scoring (12-20+ characters)
- Character variety (upper, lower, digits, special)
- Common pattern detection
- Real-time feedback

## Limitations

### Educational Environment

This implementation is designed for educational purposes and includes:

- **No Persistent Storage**: Keys not saved in database
- **Session-Based**: Keys stored temporarily in Redis session
- **Rate Limiting**: Prevents excessive key generation
- **No Key Management**: Users manage their own keys offline

### Production Considerations

For production use, consider:

- Hardware Security Module (HSM) integration
- Key escrow policies (with proper governance)
- Automated key rotation
- Centralized key management system
- Audit logging for compliance
- Legal hold procedures

## Troubleshooting

### Generation Takes Too Long

**RSA-4096 generation can take 30-60 seconds**

Factors affecting speed:
- Server CPU performance
- System entropy availability
- Concurrent key generations

**Solutions:**
- Be patient, don't refresh the page
- Try 2048-bit keys if speed is critical (less secure)
- Ensure adequate system entropy

### Keys Not Downloading

**Check these items:**
1. Pop-up blocker disabled
2. Browser allows downloads
3. Keys still in session (not cleared)
4. Sufficient disk space

### Import Errors

**Common issues:**
- Wrong file format (must be .asc)
- Incorrect passphrase
- GPG not installed
- Corrupted key file

**Solutions:**
- Re-download keys from generation page
- Verify passphrase spelling
- Install GPG: `brew install gnupg` (macOS) or `apt-get install gnupg` (Linux)

## Use Cases

### Encrypted Email

1. Generate keypair
2. Share public key with contacts
3. Configure email client (Thunderbird, etc.)
4. Send/receive encrypted emails

### Secure File Encryption

```bash
# Encrypt file
gpg --encrypt --recipient you@example.com document.pdf

# Decrypt file
gpg --decrypt document.pdf.gpg > document.pdf
```

### Digital Signatures

```bash
# Sign file
gpg --sign document.pdf

# Verify signature
gpg --verify document.pdf.gpg
```

### SSH Authentication

```bash
# Export SSH public key from PGP key
gpg --export-ssh-key you@example.com > ~/.ssh/id_rsa_from_pgp.pub
```

## Compliance

### Standards

- **OpenPGP**: RFC 4880
- **RSA Algorithm**: PKCS #1 v2.2
- **Key Length**: NIST SP 800-57 recommendations
- **Random Number Generation**: /dev/urandom (Linux)

### Educational Context

This implementation is for **security training** purposes:
- Demonstrates secure key generation
- Shows proper passphrase handling
- Illustrates OpenPGP standards
- Provides hands-on cryptography experience

**Not for:**
- Classified information
- Production cryptographic operations
- Financial transactions
- Healthcare data (HIPAA)

## References

- [OpenPGP Standard (RFC 4880)](https://tools.ietf.org/html/rfc4880)
- [NIST Key Management Guidelines](https://csrc.nist.gov/publications/detail/sp/800-57-part-1/rev-5/final)
- [GnuPG Documentation](https://www.gnupg.org/documentation/)
- [Python GnuPG Library](https://github.com/vsajip/python-gnupg)

---

**© 2026 Social Market - Educational Use Only**
