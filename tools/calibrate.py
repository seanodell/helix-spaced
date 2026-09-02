"""Probe real Helix for ground-truth selection state after a key sequence.

Spawns hx in a pty, sends keys, then deletes the selection and diffs the file
to recover the exact selected spans. A second run collapses to the cursor first
(`;`) to recover head position, which yields range direction.
"""
import fcntl
import glob
import json
import os
import pty
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CONFIG = """[editor]
auto-format = false
auto-completion = false
auto-pairs = false
[editor.lsp]
enable = false
"""

KEYMAP = {"<esc>": "\x1b", "<ret>": "\r", "<tab>": "\t", "<space>": " ",
          "<backspace>": "\x7f", "<lt>": "<", "<gt>": ">", "<minus>": "-", "<percent>": "%"}


def _runtime():
    for c in sorted(glob.glob("/opt/homebrew/Cellar/helix/*/libexec/runtime"), reverse=True):
        return c
    return os.environ.get("HELIX_RUNTIME", "")


def tokenize(seq):
    out, i = [], 0
    while i < len(seq):
        if seq[i] == "<" and ">" in seq[i:]:
            j = seq.index(">", i)
            out.append(seq[i:j + 1]); i = j + 1
        else:
            out.append(seq[i]); i += 1
    return out


def encode(tok):
    if tok in KEYMAP:
        return KEYMAP[tok]
    if tok.startswith("<A-") and tok.endswith(">"):
        return "\x1b" + tok[3:-1]
    if tok.startswith("<C-") and tok.endswith(">"):
        return chr(ord(tok[3:-1].lower()) - 96)
    if tok.startswith("<") and len(tok) > 1:
        raise ValueError(f"unknown key {tok}")
    return tok


def _respond(fd, chunk):
    if b"\x1b[c" in chunk or b"\x1b[0c" in chunk:
        os.write(fd, b"\x1b[?62;1;6;9;15;22c")
    if b"\x1b[?u" in chunk:
        os.write(fd, b"\x1b[?0u")
    if b"\x1b[>q" in chunk:
        os.write(fd, b"\x1bP>|xterm(370)\x1b\\")
    if b"\x1b[5n" in chunk:
        os.write(fd, b"\x1b[0n")
    if b"\x1b[6n" in chunk:
        os.write(fd, b"\x1b[1;1R")


def run(text, keys, timeout=10.0):
    d = Path(tempfile.mkdtemp(prefix="hxcal-"))
    (d / "config.toml").write_text(CONFIG)
    f = d / "buf.txt"
    f.write_text(text)
    env = dict(os.environ, HELIX_RUNTIME=_runtime())
    m, s = pty.openpty()
    fcntl.ioctl(s, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    os.set_blocking(m, False)
    p = subprocess.Popen(["hx", "-c", str(d / "config.toml"), str(f)],
                         stdin=s, stdout=s, stderr=s, env=env, preexec_fn=os.setsid)
    os.close(s)
    screen = []

    def drain(dur):
        end = time.time() + dur
        while time.time() < end:
            r, _, _ = select.select([m], [], [], 0.02)
            if r:
                try: chunk = os.read(m, 65536)
                except OSError: return
                if chunk:
                    screen.append(chunk); _respond(m, chunk)

    drain(1.0)
    for tok in tokenize(keys):
        os.write(m, encode(tok).encode())
        drain(0.05)
    drain(0.25)
    os.write(m, b"\x1b")
    drain(0.15)
    os.write(m, b":wq\r")
    end = time.time() + timeout
    while p.poll() is None and time.time() < end:
        drain(0.1)
    if p.poll() is None:
        p.kill(); p.wait()
    drain(0.05)
    os.close(m)
    out = f.read_text()
    shutil.rmtree(d, ignore_errors=True)
    return out, b"".join(screen).decode("utf8", "replace")


MARK = "@"


def _marked_spans(before, after):
    """Indices overwritten by MARK, grouped into contiguous spans.

    Length-preserving, so alignment is exact -- no diff ambiguity. Helix appends a
    trailing newline on write, which is trimmed before comparing.
    """
    if len(after) == len(before) + 1 and after.endswith("\n"):
        after = after[:-1]
    if len(after) != len(before):
        return None
    hits = [i for i, c in enumerate(after) if c == MARK and before[i] != MARK]
    spans, i = [], 0
    while i < len(hits):
        j = i
        while j + 1 < len(hits) and hits[j + 1] == hits[j] + 1:
            j += 1
        spans.append((hits[i], hits[j] + 1))
        i = j + 1
    return spans


def _norm(s, original):
    if s.endswith("\n\n") and not original.endswith("\n\n"):
        return s[:-1]
    return s


def probe(case):
    try:
        return _probe(case)
    except Exception as e:
        return {"text": case["text"], "keys": case["keys"], "error": f"{type(e).__name__}: {e}"}


def _probe(case):
    text, keys = case["text"], case["keys"]
    final, _ = run(text, keys)
    final = _norm(final, text)
    sel_after, _ = run(text, keys + "r" + MARK)
    cur_after, _ = run(text, keys + ";r" + MARK)
    spans = _marked_spans(final, sel_after)
    cursors = _marked_spans(final, cur_after)
    if spans is None or cursors is None:
        return {"text": text, "keys": keys, "result": final,
                "error": "length changed", "raw": sel_after}
    ranges = []
    for a, b in spans:
        c = next((cs for cs in cursors if a <= cs[0] < b), None)
        if c and b - a > 1 and c[0] == a:
            ranges.append({"anchor": b, "head": a})
        else:
            ranges.append({"anchor": a, "head": b})
    return {"text": text, "keys": keys, "result": final, "spans": spans, "ranges": ranges}


def marked(text, spans):
    out, prev = "", 0
    for a, b in spans:
        out += text[prev:a] + "[" + text[a:b] + "]"
        prev = b
    return out + text[prev:]


def main():
    cases = json.load(open(sys.argv[1])) if len(sys.argv) > 1 and Path(sys.argv[1]).exists() \
        else json.loads(sys.argv[1])
    with ThreadPoolExecutor(max_workers=int(os.environ.get("HXCAL_WORKERS", "8"))) as ex:
        results = list(ex.map(probe, cases))
    if os.environ.get("HXCAL_JSON"):
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            if "ranges" not in r:
                print(f"{r['keys']!r:>16} ERR  {r.get('error')} {r.get('raw','')!r}")
                continue
            d = "".join("<" if x["head"] < x["anchor"] else ">" for x in r["ranges"])
            print(f"{r['keys']!r:>16} {d:<4} {marked(r['result'], r['spans'])!r}")


if __name__ == "__main__":
    main()
