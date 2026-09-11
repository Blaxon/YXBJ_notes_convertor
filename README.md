# YXBJ Notes Convertor

Decrypt a Yinxiang Biji (印象笔记) / Evernote `.notes` export whose note
content is encrypted (`encoding="base64:aes"`, the `ENC0` format), and dump
each note's content out as a plain `.html` file you can open in any
browser.

## Why this exists

Yinxiang Biji / Evernote's Mac client can produce a local `.notes`
backup/export that looks like a normal `.enex` export, except every
`<content>` element is encrypted. There is **no password prompt** when you
create this export, and — importantly — there's no user password needed
to decrypt it either: the app derives its keys from a constant that is
hardcoded into the client binary itself, combined with a random salt
stored in the file. Because that "secret" lives in the app, not in your
head, any `.notes` file produced by this app can be decrypted without
knowing any password.

This was cross-checked against the C# implementation in
[HNIdesu/YinxiangbijiConverter](https://github.com/HNIdesu/YinxiangbijiConverter),
which independently reverse-engineered the same constant and algorithm.

## Requirements

- Python 3.8+
- [pycryptodome](https://pypi.org/project/pycryptodome/)

## Install

macOS ships a Homebrew-managed Python that blocks global `pip install`, so
using a virtual environment is the simplest path on any platform:

```bash
git clone git@github.com:Blaxon/YXBJ_notes_convertor.git
cd YXBJ_notes_convertor

python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

## Usage

```bash
python3 yxbj_decrypt.py "/path/to/My Notes.notes"
```

This writes one `.html` file per note (named `NNN_<title>.html`) into a
`decrypted_notes/` folder created next to your input file.

Custom output location:

```bash
python3 yxbj_decrypt.py "/path/to/My Notes.notes" -o /path/to/output_dir
```

### Getting a `.notes` export

In the Evernote / Yinxiang Biji Mac app: select the notes or notebook you
want, then **File → Export Notes...** and choose the `.notes` format.

### Example output

```
Found 62 notes in /path/to/My Notes.notes
Writing decrypted notes to /path/to/decrypted_notes

[1] 'My First Note': OK -> 001_My First Note.html
[2] 'Shopping List': OK -> 002_Shopping List.html
...
Done. 62 decrypted, 0 failed, 0 skipped (not encrypted).
```

Each output file contains the note's raw ENML/HTML body (an `<en-note>`
document) — open it directly in a browser to read it, or feed it into your
own Markdown/text converter.

## Scope & limitations

- Only decrypts the note **content** (title text is already stored
  unencrypted in the export). Embedded resources/attachments are untouched
  because they aren't encrypted in this format to begin with.
- Verified against Evernote Mac / Yinxiang Biji Mac client version 9.8.x.
  If a future client version changes the embedded constant, every note
  will fail with `HMAC mismatch` rather than silently producing garbage —
  that's a safe failure mode, not data corruption.
- This tool only reads your own local export file. It does not connect to
  any Evernote/Yinxiang service or account.

## How it works (technical)

Each encrypted `<content>` block, once base64-decoded, has this layout:

```
"ENC0" (4 bytes magic)
salt1  (16 bytes) -- for the AES key
salt2  (16 bytes) -- for the HMAC verification key
iv     (16 bytes)
ciphertext (variable length, AES-128-CBC, PKCS7-padded + 1 extra byte)
hmac   (32 bytes, HMAC-SHA256 over everything before it)
```

Both `salt1` and `salt2` are run through the same key-derivation routine:
a fixed 40-byte constant (`{22C58AC3-F1C7-4D96-8B88-5E4BBF505817}`) is used
as an HMAC-SHA256 key across 50,000 rounds, repeatedly hashing a running
nonce (seeded from the salt) and XOR-accumulating the first 16 bytes of
each round's digest into the output key. This is a bespoke construction,
not standard PBKDF2, but is deterministic and requires no secret input
beyond the salts already present in the file.

The resulting `salt1`-derived key decrypts the ciphertext (AES-128-CBC);
the `salt2`-derived key verifies the trailing HMAC before any decryption
is trusted.

## License

MIT — see [LICENSE](LICENSE).

## Credits

Algorithm cross-referenced against
[HNIdesu/YinxiangbijiConverter](https://github.com/HNIdesu/YinxiangbijiConverter).
