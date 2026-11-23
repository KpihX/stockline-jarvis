"""Markdown slide parser -> structured Slide objects (no drawing, no geometry)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SLIDES_DIR = Path(__file__).resolve().parent.parent / "slides"
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass
class Bullet:
    level: int
    text: str

    @property
    def cells(self) -> list[str]:
        return [self.text]


@dataclass
class Column:
    name: str
    colour: str
    bullets: list[Bullet] = field(default_factory=list)
    body: str = ""


@dataclass
class Section:
    bullets: list[Bullet] = field(default_factory=list)


@dataclass
class Slide:
    number: int
    path: Path
    layout: str
    meta: dict[str, str]
    head: str = ""
    sub: str = ""
    columns: list[Column] = field(default_factory=list)
    bullets: list[Bullet] = field(default_factory=list)
    notes: str = ""

    @property
    def figure(self) -> str:
        return self.meta.get("figure", "")

    @property
    def image(self) -> str:
        return self.meta.get("image", "")

    @property
    def caption(self) -> str:
        return self.meta.get("caption", "")

    @property
    def is_annexe(self) -> bool:
        return self.meta.get("annexe", "").lower() in ("1", "true", "yes")

    @property
    def label(self) -> str:
        return self.meta.get("_label", str(self.number))

    @property
    def depth(self) -> int:
        all_b = [*self.bullets, *(b for c in self.columns for b in c.bullets)]
        return max((b.level for b in all_b), default=0)

    @property
    def line_count(self) -> int:
        return len(self.bullets)

    @property
    def sections(self) -> list[Section]:
        return [Section(self.bullets), *(Section(c.bullets) for c in self.columns)]


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    _, block, body = text.split("---", 2)
    meta: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, v = line.split(":", 1)
            v = v.strip()
            if len(v) > 1 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            meta[k.strip()] = v
    return meta, body


def _parse_bullet(line: str) -> Bullet | None:
    m = re.match(r"^( *)- (.+)$", line)
    if not m:
        return None
    lvl = min(1, len(m.group(1)) // 2)
    return Bullet(level=lvl, text=m.group(2).strip())


def parse(path: Path) -> Slide:
    meta, body = _front_matter(_COMMENT.sub("", path.read_text(encoding="utf-8")))
    layout = meta.get("layout", meta.get("kind", "figure"))
    slide = Slide(number=0, path=path, layout=layout, meta=meta)

    section = "body"
    col: Column | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        txt = "\n".join(buf).strip("\n")
        if section == "notes":
            slide.notes = txt.strip()
        elif col is not None:
            col.body = txt
        buf = []

    for line in body.splitlines():
        if line.startswith("## "):
            flush()
            label = line[3:].strip()
            if label.lower() == "notes":
                section, col = "notes", None
                continue
            m = re.match(r"^(.*?)\s*\{(\w+)\}\s*$", label)
            cname, colour = (m.group(1), m.group(2)) if m else (label, "emerald")
            col = Column(name=cname.strip(), colour=colour)
            slide.columns.append(col)
            section = "column"
            continue
        if section == "body" and line.startswith("# "):
            slide.head = line[2:].strip()
            continue
        if section == "body" and line.startswith("> "):
            sub_line = line[2:].strip()
            slide.sub = f"{slide.sub}  {sub_line}".strip() if slide.sub else sub_line
            continue
        if section != "notes" and (b := _parse_bullet(line)):
            if col is not None:
                col.bullets.append(b)
            else:
                slide.bullets.append(b)
            continue
        buf.append(line)
    flush()
    return slide


def load() -> list[Slide]:
    files = sorted(SLIDES_DIR.glob("*.md"))
    if not files:
        raise SystemExit(f"no slides under {SLIDES_DIR}")
    slides = [parse(p) for p in files]
    n_main, n_annex = 0, 0
    for s in slides:
        if s.is_annexe:
            n_annex += 1
            s.meta["_label"] = f"A{n_annex}"
        else:
            n_main += 1
            s.number = n_main
            s.meta["_label"] = str(n_main)
    return slides
