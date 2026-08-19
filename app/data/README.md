# Word lists

`bip39_english.txt` — the BIP-39 English wordlist (2048 words), from
<https://github.com/bitcoin/bips/blob/master/bip-0039/english.txt>.

Chosen because it is designed for exactly this job: every word is unique in its
first four letters, there are no confusable pairs, and 2048 entries means each
word contributes exactly 11 bits of entropy. That makes the strength of a
generated passphrase a number you can state honestly rather than a colour on a
meter.
