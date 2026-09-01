"""
Self-extraction companion for McLegal_Replication_Guide.docx.

The replication guide embeds every project source file byte-exactly between
marker paragraphs. This script re-materializes all of them onto disk and
verifies each against the SHA-256 recorded at embed time — so the rebuilt
tree is PROVEN identical, not assumed.

Pure stdlib on purpose: this is the bootstrap step on a fresh machine, run
before pip has installed anything.

Usage:
    python extract_from_docx.py <path-to-guide.docx> <target-dir>

IMPORTANT: run this against the ORIGINAL .docx file. Do not open-and-resave
it from Word first (a resave can rewrite the underlying XML).

Marker format (one paragraph each):
    <<<BEGIN-FILE>>> path=<relpath> mode=<text|b64> eol=<LF|CRLF|NA> eofnl=<0|1|NA> sha256=<hex>
    ... one paragraph per line of file content ...
    <<<END-FILE>>>
"""

import base64
import hashlib
import re
import sys
import zipfile
from html import unescape
from pathlib import Path

BEGIN = "\u27e6BEGIN-FILE\u27e7"   # ⟦BEGIN-FILE⟧
END = "\u27e6END-FILE\u27e7"       # ⟦END-FILE⟧

_P_RE = re.compile(rb"<w:p(?:\s[^>]*)?>.*?</w:p>|<w:p(?:\s[^>]*)?/>", re.DOTALL)
_RUN_CONTENT_RE = re.compile(rb"<w:(t|tab|br|cr)\b[^>]*?(?:/>|>(.*?)</w:\1>)", re.DOTALL)


def paragraphs_text(document_xml: bytes):
    """Yield the plain text of every paragraph in document.xml, in order.
    <w:t> content is XML-unescaped; <w:tab/> becomes \\t. One string per
    <w:p>, with no newline characters inside."""
    for p_match in _P_RE.finditer(document_xml):
        chunk = p_match.group(0)
        parts = []
        for m in _RUN_CONTENT_RE.finditer(chunk):
            kind = m.group(1)
            if kind == b"t":
                parts.append(unescape((m.group(2) or b"").decode("utf-8")))
            elif kind == b"tab":
                parts.append("\t")
            # w:br / w:cr never occur inside embedded code lines
        yield "".join(parts)


def parse_marker(line: str) -> dict:
    fields = {}
    body = line[len(BEGIN):].strip()
    # sha256 is last; path may contain spaces, so parse known keys right-to-left
    for key in ("sha256", "eofnl", "eol", "mode"):
        idx = body.rfind(f" {key}=")
        fields[key] = body[idx + len(key) + 2:].strip()
        body = body[:idx]
    assert body.startswith("path="), f"bad marker: {line!r}"
    fields["path"] = body[len("path="):].strip()
    return fields


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    docx_path, target = Path(sys.argv[1]), Path(sys.argv[2])
    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml")

    results = []
    current = None  # (fields, [lines])
    for text in paragraphs_text(xml):
        if text.startswith(BEGIN):
            current = (parse_marker(text), [])
        elif text.startswith(END):
            fields, lines = current
            current = None
            if fields["mode"] == "b64":
                content = base64.b64decode("".join(lines))
            else:
                eol = "\r\n" if fields["eol"] == "CRLF" else "\n"
                content = eol.join(lines).encode("utf-8")
                if fields["eofnl"] == "1":
                    content += eol.encode()
            actual = hashlib.sha256(content).hexdigest()
            ok = actual == fields["sha256"]
            out = target / fields["path"]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(content)
            results.append((fields["path"], ok))
            print(f"{'OK  ' if ok else 'FAIL'} {fields['path']} ({len(content):,} bytes)")
        elif current is not None:
            current[1].append(text)

    failed = [p for p, ok in results if not ok]
    print(f"\n{len(results)} files extracted to {target}")
    if failed:
        print(f"SHA-256 MISMATCH on {len(failed)} file(s): {failed}")
        print("Do NOT trust these copies — re-extract from the original, unmodified .docx.")
        sys.exit(1)
    print("All SHA-256 checks passed — extracted tree is byte-identical to the original project.")


if __name__ == "__main__":
    main()
