#!/usr/bin/env python3
"""
yxbj_decrypt.py

Decrypt a Yinxiang Biji / Evernote ".notes" export whose <content> blocks
are encoded as encoding="base64:aes" (the "ENC0" format), and write out the
decrypted note bodies as standalone HTML files.

Background
----------
Yinxiang Biji (印象笔记, the Evernote client for the Chinese market) and
Evernote's Mac client can produce a local ".notes" backup/export file that
looks like a normal ENEX export, except every <content> element is
encrypted (encoding="base64:aes", with an "ENC0" magic header).

This is NOT protected by a user-chosen password. The app derives its AES
and HMAC keys from a hardcoded constant baked into the client binary, run
through a custom 50,000-round HMAC-SHA256 key-derivation loop together with
a random salt stored in the file. Since the "secret" is a fixed constant
embedded in the app itself rather than anything only the user knows, any
".notes" file produced by this app can be decrypted without knowing any
password.

This implementation was derived independently and cross-checked against
the C# reference implementation in
https://github.com/HNIdesu/YinxiangbijiConverter (Program.cs), which
reverse-engineered the same constant and algorithm.

Scope / limitations
--------------------
- Only handles the note <content> field (the note body/text). Embedded
  resources (images, attachments) are left untouched -- they are not
  encrypted in this format to begin with.
- Only tested against the "ENC0" scheme used by Evernote Mac / Yinxiang
  Biji Mac 9.8.x. If a future app version changes the embedded constant,
  the HMAC verification step will simply fail for every note (you'll see
  "HMAC mismatch" errors below) rather than silently producing garbage.

Usage
-----
    python3 yxbj_decrypt.py path/to/export.notes [-o output_dir]

Writes one .html file per note into "<output_dir>/decrypted_notes"
(default: a "decrypted_notes" folder next to the input file).
"""
import argparse
import base64
import hashlib
import hmac
import html
import os
import re
import sys

try:
    from Crypto.Cipher import AES
except ImportError:
    print(
        "Missing dependency 'pycryptodome'.\n"
        "Install it first, e.g.:\n"
        "    python3 -m venv venv && source venv/bin/activate\n"
        "    pip install -r requirements.txt\n",
        file=sys.stderr,
    )
    sys.exit(1)

# Hardcoded constant embedded in the Evernote / Yinxiang Biji client binary.
# This is not a user secret -- see module docstring.
HMAC_KEY = b"{22C58AC3-F1C7-4D96-8B88-5E4BBF505817}"
KDF_ROUNDS = 50000

NOTE_RE = re.compile(r"<note>(.*?)</note>", re.S)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
CONTENT_RE = re.compile(
    r'<content encoding="base64:aes"><!\[CDATA\[(.*?)\]\]></content>', re.S
)


def generate_key(salt16: bytes) -> bytes:
    """Reproduces the client's custom HMAC-chain key derivation.

    Not PBKDF2: each round re-hashes the running nonce with HMAC-SHA256
    under the fixed HMAC_KEY, then XORs the first 16 bytes of that round's
    digest into the output key. Iterated 50,000 times.
    """
    nonce = bytearray(20)
    nonce[0:16] = salt16
    nonce[19] = 1
    key = bytearray(16)
    nonce_bytes = bytes(nonce)
    for _ in range(KDF_ROUNDS):
        nonce_bytes = hmac.new(HMAC_KEY, nonce_bytes, hashlib.sha256).digest()
        for j in range(16):
            key[j] ^= nonce_bytes[j]
    return bytes(key)


def unpad_pkcs7(data: bytes) -> bytes:
    pad_len = data[-1]
    if pad_len < 1 or pad_len > 16 or pad_len > len(data):
        raise ValueError("bad PKCS7 padding")
    return data[:-pad_len]


def decrypt_content(raw: bytes) -> str:
    """Decrypt one <content encoding="base64:aes"> payload (already base64-decoded).

    Wire format: b"ENC0" + salt1(16) + salt2(16) + iv(16) + ciphertext + hmac(32)
    """
    if raw[:4] != b"ENC0":
        raise ValueError("missing ENC0 magic header")

    salt1 = raw[4:20]
    salt2 = raw[20:36]
    iv = raw[36:52]
    ciphertext = raw[52:-32]
    stored_hmac = raw[-32:]

    aes_key = generate_key(salt1)
    hmac_key = generate_key(salt2)

    computed_hmac = hmac.new(hmac_key, raw[:-32], hashlib.sha256).digest()
    if not hmac.compare_digest(computed_hmac, stored_hmac):
        raise ValueError("HMAC mismatch (unexpected format/version)")

    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    plaintext = unpad_pkcs7(cipher.decrypt(ciphertext))
    plaintext = plaintext[:-1]  # client appends one extra trailing byte after padding
    return plaintext.decode("utf-8", errors="replace")


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    return name[:120] if name else "untitled"


def main():
    parser = argparse.ArgumentParser(
        description="Decrypt a Yinxiang Biji / Evernote .notes export (ENC0 format)."
    )
    parser.add_argument("input", help="Path to the .notes (or .enex) export file")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output directory (default: 'decrypted_notes' next to the input file)",
    )
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = f.read()

    out_dir = args.output or os.path.join(
        os.path.dirname(os.path.abspath(args.input)), "decrypted_notes"
    )
    os.makedirs(out_dir, exist_ok=True)

    notes = NOTE_RE.findall(data)
    print(f"Found {len(notes)} notes in {args.input}")
    print(f"Writing decrypted notes to {out_dir}\n")

    ok = 0
    failed = []
    skipped = 0
    for i, note_block in enumerate(notes, 1):
        title_match = TITLE_RE.search(note_block)
        title = html.unescape(title_match.group(1)) if title_match else f"note_{i}"

        content_match = CONTENT_RE.search(note_block)
        if not content_match:
            skipped += 1
            print(f"[{i}] '{title}': not encrypted (or no content), skipping")
            continue

        raw = base64.b64decode(content_match.group(1))
        try:
            plaintext = decrypt_content(raw)
        except Exception as e:
            failed.append((title, str(e)))
            print(f"[{i}] '{title}': FAILED ({e})")
            continue

        fname = f"{i:03d}_{sanitize_filename(title)}.html"
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as out:
            out.write(plaintext)
        ok += 1
        print(f"[{i}] '{title}': OK -> {fname}")

    print(f"\nDone. {ok} decrypted, {len(failed)} failed, {skipped} skipped (not encrypted).")
    sys.exit(1 if failed and ok == 0 else 0)


if __name__ == "__main__":
    main()
