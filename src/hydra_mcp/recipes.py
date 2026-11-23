"""recipes.py — run the Archive Workflow's command-line recipes by name (gap G17).

The recipes are small read-only programs (bash with PowerShell twins, and shared jq filters) that turn a document or
an archive into the JSON the other tools take. This module runs only the recipes listed in RECIPES, from one folder,
with the arguments each one names, a time limit, and no shell string: every argument goes to the program as it is.

The folder is $HYDRA_RECIPES, else the `Archive Workflow/recipes` folder beside the hydra-mcp checkout. The shell is
$HYDRA_RECIPES_SHELL: `powershell` (the default on Windows), `bash` (the default elsewhere) or `wsl` (bash in the WSL
distribution $HYDRA_WSL_DISTRO, default Debian, once its packages are installed)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from hydra_mcp import core

TIMEOUT, MAX_TIMEOUT = 120, 600

AUDIT_CHECKS = ("summary", "fill", "unsourced", "nonotes", "undated", "open", "status", "samename", "dangling", "names")

RECIPES = {
    "intake": {
        "args": {"doc": "the document's full path"},
        "gives": "{file, path, sha256, bytes, type, pages, text_layer, title, author, producer, created, outline}",
        "use": "the run's intake file; text_layer 'scan' means OCR first",
    },
    "outline": {
        "args": {"doc": "the document's full path",
                 "headings": "true to find headings in the text when the bookmarks are only scan batches"},
        "gives": "[{level, page, title, from}]",
        "use": "the parts to read, with their pages; titles are for planning, quotes still come from read_file",
    },
    "names": {
        "args": {"doc": "the document's full path", "from": "first page (PDF)", "to": "last page (PDF)",
                 "min": "drop names seen fewer times (default 2)"},
        "gives": "[{name, count}]",
        "use": "look each name up with find_entities; a name is never proof two records are one entity",
    },
    "findquote": {
        "args": {"doc": "the PDF's full path", "quotes": "the quotes to place, a list"},
        "gives": "[{quote, pages}]",
        "use": "PDF pages, for cite's pdfPages; a quote with pages [] is not in the text word for word: fix it before check_records",
    },
    "table": {
        "args": {"doc": "the PDF's full path", "from": "first page", "to": "last page"},
        "gives": "{tsv, rows}",
        "use": "check the columns, put FtM property names in the first row, then run tsv2records",
    },
    "tsv2records": {
        "args": {"tsv": "tab-separated text whose first row names FtM properties (\";\" splits values)",
                 "schema": "the records' schema", "source": "the source id, optional"},
        "gives": "[{id, schema, properties}]",
        "use": "add each record's exact sentence to notes, then check_records and save",
    },
    "audit": {
        "args": {"check": " | ".join(AUDIT_CHECKS)},
        "gives": "a list (or counts) from the archive's records",
        "use": "fix lists: unsourced -> cite, nonotes -> amend_records, open/undated -> open_ends, "
               "samename -> open_questions (a question, never a merge), dangling -> stubs, status -> vocabularies",
    },
}

_SH = {"intake": "intake", "outline": "outline", "names": "names", "findquote": "findquote", "table": "table"}


def folder() -> Path:
    env = os.environ.get("HYDRA_RECIPES", "").strip()
    d = Path(env).expanduser() if env else Path(__file__).resolve().parents[3] / "Archive Workflow" / "recipes"
    if not (d / "audit.jq").is_file():
        raise core.IngestError(f"no recipes folder at {d}: set HYDRA_RECIPES to the Archive Workflow's recipes folder")
    return d


def shell() -> str:
    s = os.environ.get("HYDRA_RECIPES_SHELL", "").strip().lower() or ("powershell" if sys.platform == "win32" else "bash")
    if s not in ("powershell", "bash", "wsl"):
        raise core.IngestError(f"HYDRA_RECIPES_SHELL is '{s}': use powershell, bash or wsl")
    return s


def to_wsl(p: str | Path) -> str:
    """E:\\a\\b -> /mnt/e/a/b."""
    s = str(p).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", s)
    return f"/mnt/{m.group(1).lower()}/{m.group(2)}" if m else s


def _wsl() -> list[str]:
    return ["wsl", "-d", os.environ.get("HYDRA_WSL_DISTRO", "Debian").strip() or "Debian", "--"]


def _script(name: str, args: list, paths: set[int]) -> list[str]:
    """The command for one .sh / .ps1 recipe. `args` are (flag-or-None, value) pairs; `paths` marks which are paths."""
    d, sh = folder(), shell()
    if sh == "powershell":
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
               "-File", str(d / f"{_SH[name]}.ps1")]
        for flag, value in args:
            cmd += ([flag] if flag else []) + [str(value)]
        return cmd
    vals = [to_wsl(v) if (i in paths and sh == "wsl") else str(v) for i, (_, v) in enumerate(args)]
    script = d / f"{_SH[name]}.sh"
    return (_wsl() + ["bash", to_wsl(script)] if sh == "wsl" else ["bash", str(script)]) + vals


def _jq(args: list[str], files: list[Path]) -> list[str]:
    if shell() == "wsl":
        return _wsl() + ["jq", *[to_wsl(a) if a.endswith(".jq") else a for a in args], *map(to_wsl, files)]
    jq = shutil.which("jq")
    if not jq:
        raise core.IngestError("jq is not on the PATH: install jq, or set HYDRA_RECIPES_SHELL=wsl")
    return [jq, *args, *map(str, files)]


def _exec(cmd: list[str], timeout: int, stdin: bytes | None = None) -> str:
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        raise core.IngestError(f"{cmd[0]} was not found: check HYDRA_RECIPES_SHELL") from None
    except subprocess.TimeoutExpired:
        raise core.IngestError(f"the recipe took longer than {timeout} s: give a smaller page range, "
                               f"or a larger timeout (at most {MAX_TIMEOUT})") from None
    out = r.stdout.decode("utf-8", errors="replace").lstrip("\ufeff")
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise core.IngestError(f"the recipe failed (exit {r.returncode}): " + (" ".join(err[-3:]) or "no message"))
    return out


def _json(out: str):
    try:
        return json.loads(out)
    except ValueError:
        raise core.IngestError("the recipe did not print JSON: " + out.strip()[:300]) from None


def _int(a: dict, key: str, required: bool = False) -> int | None:
    v = a.get(key)
    if v in (None, ""):
        if required:
            raise core.IngestError(f"give `{key}` in args")
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise core.IngestError(f"args.{key} must be a whole number, not {v!r}") from None
    if n < 1:
        raise core.IngestError(f"args.{key} must be 1 or more")
    return n


def _doc(a: dict, pdf: bool = False) -> Path:
    p = core.resolve_file(None, a.get("doc") or a.get("pdf") or a.get("path") or "")
    if pdf and p.suffix.lower() != ".pdf":
        raise core.IngestError(f"{p.name} is not a PDF: this recipe reads PDFs only")
    return p


def listing() -> dict:
    return {"recipes": {n: {"args": r["args"], "gives": r["gives"], "use": r["use"]} for n, r in RECIPES.items()}}


def run(name: str | None, args: dict | None, archive: str | None = None, timeout: int | None = None) -> dict:
    if not name:
        return listing()
    if name not in RECIPES:
        raise core.IngestError(f"no recipe '{name}': the recipes are {', '.join(RECIPES)}")
    a = dict(args or {})
    t = max(1, min(int(timeout or TIMEOUT), MAX_TIMEOUT))
    d = folder()

    if name == "intake":
        result = _json(_exec(_script(name, [("-Doc", _doc(a))], {0}), t))
    elif name == "outline":
        pairs = [("-Doc", _doc(a))] + ([("-Mode", "headings")] if a.get("headings") in (True, "true", "headings") else [])
        result = _json(_exec(_script(name, pairs, {0}), t))
    elif name == "names":
        frm, to, mn = _int(a, "from"), _int(a, "to"), _int(a, "min")
        if shell() == "powershell":
            pairs = [("-Doc", _doc(a))] + [(f, v) for f, v in (("-From", frm), ("-To", to), ("-Min", mn)) if v]
        else:                                   # names.sh DOC [FROM TO] [MIN]: positional, "" for a page left open
            pairs = [(None, _doc(a)), (None, frm or ""), (None, to or ""), (None, mn or 2)]
        result = _json(_exec(_script(name, pairs, {0}), t))
    elif name == "findquote":
        quotes = a.get("quotes", a.get("quote"))
        quotes = [quotes] if isinstance(quotes, str) else list(quotes or [])
        quotes = [" ".join(str(q).split()) for q in quotes if str(q).strip()]
        if not quotes:
            raise core.IngestError("give `quotes` in args: the sentences to place, a list")
        doc = _doc(a, pdf=True)
        if shell() == "powershell":            # PowerShell 5.1 splits an argument holding a double quote: use a file
            with tempfile.TemporaryDirectory() as tmp:
                qf = Path(tmp) / "quotes.txt"
                qf.write_text("\n".join(quotes) + "\n", encoding="utf-8")
                result = _json(_exec(_script(name, [("-Pdf", doc), ("-QuoteFile", qf)], {0}), t))
        else:
            result = _json(_exec(_script(name, [(None, doc)] + [(None, q) for q in quotes], {0}), t))
    elif name == "table":
        doc, frm, to = _doc(a, pdf=True), _int(a, "from", True), _int(a, "to", True)
        if to < frm:
            raise core.IngestError("args.to comes before args.from")
        tsv = _exec(_script(name, [("-Pdf", doc), ("-From", frm), ("-To", to)], {0}), t).replace("\r\n", "\n")
        result = {"tsv": tsv, "rows": [line.split("\t") for line in tsv.splitlines() if line.strip()]}
    elif name == "tsv2records":
        tsv, schema = str(a.get("tsv") or ""), str(a.get("schema") or "").strip()
        if not tsv.strip():
            raise core.IngestError("give `tsv` in args: the table's text, first row the FtM property names")
        if not schema:
            raise core.IngestError("give `schema` in args: the records' schema, such as Person")
        jq_args = ["-R", "-s", "--arg", "schema", schema]
        if str(a.get("source") or "").strip():
            jq_args += ["--arg", "source", str(a["source"]).strip()]
        result = _json(_exec(_jq(jq_args + ["-f", str(d / "tsv2records.jq")], []), t, stdin=tsv.encode("utf-8")))
    else:                                       # audit
        check = str(a.get("check") or "").strip()
        if check not in AUDIT_CHECKS:
            raise core.IngestError(f"give `check` in args, one of: {', '.join(AUDIT_CHECKS)}")
        root = core.open_archive(archive)
        from hydra import resources
        files = resources.record_files(root)[0]
        if not files:
            raise core.IngestError(f"{root} has no collections yet")
        result = _json(_exec(_jq(["-n", "--arg", "check", check, "-f", str(d / "audit.jq")], files), t))

    return {"recipe": name, "result": result, "use": RECIPES[name]["use"]}
