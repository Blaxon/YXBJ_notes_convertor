# YXBJ Notes Convertor

解析印象笔记导出的 `.notes` 文件并把每条笔记的内容导出为
纯 `.md`（Markdown，默认）或 `.html` 文件。

## 为什么会有这个工具

印象笔记的 Mac 客户端可以生成一种本地 `.notes` 备份/导出
文件，格式上看起来和普通的 `.enex` 导出文件类似，只是每个 `<content>`
元素都被加密了。生成这种导出文件时**不会弹出任何密码输入框**——更重要
的是，解密它也**不需要任何用户密码**：客户端是从一个硬编码在客户端
二进制文件里的常量出发，结合文件中存储的随机盐值来推导密钥的。既然这个
"秘密"是写在软件里的，而不是只有你自己知道的东西，那么任何由这个客户端
生成的 `.notes` 文件，都可以在不知道任何密码的情况下被解密。

该实现已与
[HNIdesu/YinxiangbijiConverter](https://github.com/HNIdesu/YinxiangbijiConverter)
中的 C# 实现相互印证——该项目独立逆向出了同一个常量和算法。

## 环境要求

- Python 3.8+
- [pycryptodome](https://pypi.org/project/pycryptodome/)
- [markdownify](https://pypi.org/project/markdownify/)（仅 `--format md` 默认输出需要）

## 安装

macOS 自带的 Homebrew Python 会阻止全局 `pip install`，所以不管在哪个
平台，使用虚拟环境都是最简单的方式：

```bash
git clone git@github.com:Blaxon/YXBJ_notes_convertor.git
cd YXBJ_notes_convertor

python3 -m venv venv
source venv/bin/activate      # Windows 下用: venv\Scripts\activate

pip install -r requirements.txt
```

## 使用方法

```bash
python3 yxbj_decrypt.py "/path/to/My Notes.notes"
```

这会在输入文件同目录下创建一个 `decrypted_notes/` 文件夹，并将每条笔记
转换并写成一个 `.md` 文件（命名格式为 `NNN_标题.md`）。

自定义输出目录：

```bash
python3 yxbj_decrypt.py "/path/to/My Notes.notes" -o /path/to/output_dir
```

如果想保留原始 ENML/HTML 内容而不转换为 Markdown，可以加上
`--format html`：

```bash
python3 yxbj_decrypt.py "/path/to/My Notes.notes" --format html
```

### 如何获取 `.notes` 导出文件

在 Evernote / 印象笔记 Mac 客户端中：选中要导出的笔记或笔记本，然后
**文件 → 导出笔记...**，格式选择 `.notes`。

### 输出示例

```
在 /path/to/My Notes.notes 中找到 62 条笔记
解密结果（md 格式）将写入 /path/to/decrypted_notes

[1] '我的第一条笔记'：解密成功 -> 001_我的第一条笔记.md
[2] '购物清单'：解密成功 -> 002_购物清单.md
...
完成。成功 62 条，失败 0 条，跳过 0 条（未加密）。
```

`--format md`（默认）会把 ENML 转换为常见的 Markdown 语法（标题、列表、
链接、粗斜体等），并将印象笔记特有的标签转换为对应的近似表示：

- `<en-todo>` 待办复选框 → GFM 复选框语法 `- [x]` / `- [ ]`
- `<en-media>`（图片/附件引用）→ 一段占位说明，标注附件的类型和哈希值
  （附件本身并未被提取，见下方"适用范围与限制"）

`--format html` 则直接输出该笔记原始的 ENML/HTML 正文（一个 `<en-note>`
文档）——可以直接用浏览器打开阅读，也可以自行用其他工具转换。

## 适用范围与限制

- 只解密笔记的**正文内容**（标题在导出文件中本来就是明文）。内嵌的资源
  文件/附件不会被提取，因为这种格式本身就没有对它们加密——`--format md`
  只会在原本引用附件的位置留下一段占位说明。
- 目前只在 Evernote Mac / 印象笔记 Mac 客户端 9.8.x 版本上验证通过。如果
  未来的客户端版本更换了内置常量，每条笔记都会直接报 `HMAC mismatch`
  错误，而不会静默产出乱码内容——这是一种安全的失败方式，不会造成数据
  损坏或误判。
- 本工具只读取你本地的导出文件，不会连接任何 Evernote / 印象笔记的
  服务器或账号。

## 原理说明（技术细节）

每个加密的 `<content>` 内容块，base64 解码后的数据结构如下：

```
"ENC0" (4 字节魔数)
salt1  (16 字节) —— 用于派生 AES 密钥
salt2  (16 字节) —— 用于派生 HMAC 校验密钥
iv     (16 字节)
密文    (长度不定，AES-128-CBC，PKCS7 填充)
hmac   (32 字节，对前面所有内容做 HMAC-SHA256)
```

`salt1` 和 `salt2` 都会经过同一套密钥派生流程：以一个固定的 40 字节
常量（`{22C58AC3-F1C7-4D96-8B88-5E4BBF505817}`）作为 HMAC-SHA256 的密钥，
迭代 5 万轮——每一轮都对当前的 nonce（由盐值播种）重新做一次哈希，并把
这一轮摘要的前 16 字节异或累加进输出密钥。这是一套非标准的自定义构造，
不是常见的 PBKDF2，但它是确定性的，除了文件中本就存在的盐值外，不需要
任何额外的秘密输入。

由 `salt1` 派生出的密钥用于解密密文（AES-128-CBC）；由 `salt2` 派生出
的密钥则用于在解密之前先校验末尾的 HMAC，确保数据完整可信。

## 参考资料

- [`docs/yinxiang-encryption-article.md`](docs/yinxiang-encryption-article.md)：
  官方文档《[印象笔记使用什么类型的加密？](https://www.yinxiang.com/hc/articles/%E5%8D%B0%E8%B1%A1%E7%AC%94%E8%AE%B0%E4%BD%BF%E7%94%A8%E4%BB%80%E4%B9%88%E7%B1%BB%E5%9E%8B%E7%9A%84%E5%8A%A0%E5%AF%86%EF%BC%9F/)》
  的正文存档与原始网页快照（`yinxiang-encryption-article.html`），供离线
  查阅与留档。注意：该文档描述的是笔记内"选中文本加密"功能（基于用户
  口令），与本工具处理的 `.notes` 整体导出加密（基于硬编码常量）是两套
  不同的机制，详见该存档文件末尾的编者按。

## 许可证

MIT — 详见 [LICENSE](LICENSE)。

## 致谢

算法已与
[HNIdesu/YinxiangbijiConverter](https://github.com/HNIdesu/YinxiangbijiConverter)
相互印证。
