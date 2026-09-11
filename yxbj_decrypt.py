#!/usr/bin/env python3
"""
yxbj_decrypt.py

解密印象笔记 / Evernote 导出的 ".notes" 文件——其中 <content> 内容块被编码为
encoding="base64:aes"（即 "ENC0" 格式）——并将解密后的笔记正文输出为独立的
HTML 文件。

背景说明
----------
印象笔记（面向中国市场的 Evernote 客户端）以及 Evernote 的 Mac 客户端，
都可以生成一种本地 ".notes" 备份/导出文件，格式上看起来和普通的 ENEX 导出
文件类似，只是每个 <content> 元素都被加密了（encoding="base64:aes"，并带有
"ENC0" 魔数头）。

这**并不是**由用户自己设置的密码保护的。客户端会从一个硬编码在客户端二进制
文件里的固定常量出发，结合文件中存储的随机盐值，经过自定义的 5 万轮
HMAC-SHA256 密钥派生循环，推导出 AES 密钥和 HMAC 密钥。由于这个"秘密"其实
是写死在软件里的常量，而不是只有用户本人知道的东西，所以任何由该客户端生成
的 ".notes" 文件都可以在不知道任何密码的情况下被解密。

本实现是独立编写并与
https://github.com/HNIdesu/YinxiangbijiConverter （Program.cs）中的 C# 参考
实现相互印证的，二者独立逆向出了同一个常量和算法。

适用范围 / 限制
--------------------
- 只处理笔记的 <content> 字段（笔记正文/文本）。内嵌的资源文件（图片、附件）
  不会被处理——因为这种格式本身并未对它们加密。
- 目前只在 Evernote Mac / 印象笔记 Mac 9.8.x 所使用的 "ENC0" 方案上测试过。
  如果未来的客户端版本更换了内置常量，HMAC 校验步骤会直接对每条笔记报错
  （下方会看到 "HMAC mismatch" 错误），而不会静默产出乱码内容。

用法
-----
    python3 yxbj_decrypt.py path/to/export.notes [-o output_dir]

会将每条笔记写为一个 .html 文件，输出到 "<output_dir>/decrypted_notes"
（默认：在输入文件同目录下创建 "decrypted_notes" 文件夹）。
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
        "缺少依赖库 'pycryptodome'。\n"
        "请先安装，例如：\n"
        "    python3 -m venv venv && source venv/bin/activate\n"
        "    pip install -r requirements.txt\n",
        file=sys.stderr,
    )
    sys.exit(1)

# 硬编码在 Evernote / 印象笔记客户端二进制文件中的固定常量。
# 这不是用户的私密信息——详见文件顶部的说明。
HMAC_KEY = b"{22C58AC3-F1C7-4D96-8B88-5E4BBF505817}"
KDF_ROUNDS = 50000

NOTE_RE = re.compile(r"<note>(.*?)</note>", re.S)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
CONTENT_RE = re.compile(
    r'<content encoding="base64:aes"><!\[CDATA\[(.*?)\]\]></content>', re.S
)


def generate_key(salt16: bytes) -> bytes:
    """还原客户端自定义的 HMAC 链式密钥派生算法。

    注意：这不是标准的 PBKDF2。每一轮都用固定的 HMAC_KEY 对当前的 nonce
    做一次 HMAC-SHA256 重新哈希，然后把这一轮摘要的前 16 字节异或累加进
    输出密钥，如此迭代 5 万次。
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
        raise ValueError("PKCS7 填充数据不合法")
    return data[:-pad_len]


def decrypt_content(raw: bytes) -> str:
    """解密一个 <content encoding="base64:aes"> 内容块（传入前需先做 base64 解码）。

    数据格式：b"ENC0" + salt1(16字节) + salt2(16字节) + iv(16字节) + 密文 + hmac(32字节)
    """
    if raw[:4] != b"ENC0":
        raise ValueError("缺少 ENC0 魔数头")

    salt1 = raw[4:20]
    salt2 = raw[20:36]
    iv = raw[36:52]
    ciphertext = raw[52:-32]
    stored_hmac = raw[-32:]

    aes_key = generate_key(salt1)
    hmac_key = generate_key(salt2)

    computed_hmac = hmac.new(hmac_key, raw[:-32], hashlib.sha256).digest()
    if not hmac.compare_digest(computed_hmac, stored_hmac):
        raise ValueError("HMAC 校验不匹配（格式/版本可能不符合预期）")

    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    plaintext = unpad_pkcs7(cipher.decrypt(ciphertext))
    plaintext = plaintext[:-1]  # 客户端在去除填充后还会多附加一个字节，需一并去掉
    return plaintext.decode("utf-8", errors="replace")


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    return name[:120] if name else "untitled"


def main():
    parser = argparse.ArgumentParser(
        description="解密印象笔记 / Evernote 的 .notes 导出文件（ENC0 格式）。"
    )
    parser.add_argument("input", help="待解密的 .notes（或 .enex）导出文件路径")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="输出目录（默认：在输入文件同目录下创建 'decrypted_notes' 文件夹）",
    )
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = f.read()

    out_dir = args.output or os.path.join(
        os.path.dirname(os.path.abspath(args.input)), "decrypted_notes"
    )
    os.makedirs(out_dir, exist_ok=True)

    notes = NOTE_RE.findall(data)
    print(f"在 {args.input} 中找到 {len(notes)} 条笔记")
    print(f"解密结果将写入 {out_dir}\n")

    ok = 0
    failed = []
    skipped = 0
    for i, note_block in enumerate(notes, 1):
        title_match = TITLE_RE.search(note_block)
        title = html.unescape(title_match.group(1)) if title_match else f"note_{i}"

        content_match = CONTENT_RE.search(note_block)
        if not content_match:
            skipped += 1
            print(f"[{i}] '{title}'：未加密（或无内容），已跳过")
            continue

        raw = base64.b64decode(content_match.group(1))
        try:
            plaintext = decrypt_content(raw)
        except Exception as e:
            failed.append((title, str(e)))
            print(f"[{i}] '{title}'：解密失败（{e}）")
            continue

        fname = f"{i:03d}_{sanitize_filename(title)}.html"
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as out:
            out.write(plaintext)
        ok += 1
        print(f"[{i}] '{title}'：解密成功 -> {fname}")

    print(f"\n完成。成功 {ok} 条，失败 {len(failed)} 条，跳过 {skipped} 条（未加密）。")
    sys.exit(1 if failed and ok == 0 else 0)


if __name__ == "__main__":
    main()
