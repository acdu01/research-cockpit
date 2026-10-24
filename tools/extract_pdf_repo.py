from __future__ import annotations

import re
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = ROOT / "research-cockpit-handoff.pdf"


@dataclass
class Run:
    x: float
    y: float
    text: str


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return (
        text.replace("\u00a0", " ")
        .replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
    )


class PdfRepoExtractor:
    def __init__(self, pdf_path: Path) -> None:
        self.pdf = pdf_path.read_bytes()
        self._obj_cache: dict[int, bytes] = {}
        self.cmap = self._parse_cmap(self._get_obj(4))
        self.page_order = self._page_order()

    def _get_obj(self, obj_num: int) -> bytes:
        cached = self._obj_cache.get(obj_num)
        if cached is not None:
            return cached
        match = re.search(
            rb"\n" + str(obj_num).encode() + rb" 0 obj\n(.*?)\nendobj",
            self.pdf,
            re.S,
        )
        if not match:
            raise KeyError(f"missing object {obj_num}")
        self._obj_cache[obj_num] = match.group(1)
        return self._obj_cache[obj_num]

    def _font_cmap_obj(self, obj_num: int) -> bytes:
        obj = self._get_obj(obj_num)
        match = re.search(rb"/ToUnicode (\d+) 0 R", obj)
        if not match:
            raise ValueError(f"font {obj_num} missing ToUnicode")
        return self._get_obj(int(match.group(1)))

    def _parse_cmap(self, cmap_obj: bytes) -> dict[int, str]:
        raw = self._extract_stream_bytes(cmap_obj)
        if raw is None:
            raise ValueError("missing cmap stream")
        decoded = zlib.decompress(raw).decode("latin1")
        cmap: dict[int, str] = {}
        mode: str | None = None
        for raw_line in decoded.splitlines():
            line = raw_line.strip()
            if line.endswith("beginbfrange"):
                mode = "range"
                continue
            if line.endswith("beginbfchar"):
                mode = "char"
                continue
            if line.startswith("endbf"):
                mode = None
                continue
            if mode == "range":
                match = re.match(
                    r"<([0-9A-Fa-f]+)> <([0-9A-Fa-f]+)> <([0-9A-Fa-f]+)>",
                    line,
                )
                if not match:
                    continue
                start, end, dest = [int(v, 16) for v in match.groups()]
                for offset, code in enumerate(range(start, end + 1)):
                    cmap[code] = chr(dest + offset)
            elif mode == "char":
                match = re.match(r"<([0-9A-Fa-f]+)> <([0-9A-Fa-f]+)>", line)
                if not match:
                    continue
                src, dest = [int(v, 16) for v in match.groups()]
                cmap[src] = chr(dest)
        return cmap

    def _decode_hex(self, hex_string: str) -> str:
        chars = []
        for idx in range(0, len(hex_string), 4):
            code = int(hex_string[idx : idx + 4], 16)
            chars.append(self.cmap.get(code, "?"))
        return normalize_text("".join(chars))

    def _page_order(self) -> list[int]:
        pages_obj = self._get_obj(2).decode("latin1")
        return [int(v) for v in re.findall(r"(\d+) 0 R", pages_obj)]

    def _outline_entries(self) -> list[tuple[str, int]]:
        entries: list[tuple[str, int]] = []
        pattern = re.compile(
            rb"\d+ 0 obj\n<</A<</S/GoTo/D\[(\d+) 0 R/XYZ [^\]]*\]>>"
            rb"(?:/Next \d+ 0 R)?(?:/Parent \d+ 0 R)?(?:/Prev \d+ 0 R)?"
            rb"/Title(?:\((.*?)\)|<FEFF([0-9A-Fa-f]+)>)",
            re.S,
        )
        for match in pattern.finditer(self.pdf):
            page_ref = int(match.group(1))
            ascii_title = match.group(2)
            hex_title = match.group(3)
            if hex_title:
                title = bytes.fromhex(hex_title.decode()).decode("utf-16-be")
            else:
                title = ascii_title.decode("latin1", "ignore")
            entries.append((title, page_ref))
        return entries

    def _page_runs(self, page_obj_num: int) -> list[Run]:
        page = self._get_obj(page_obj_num).decode("latin1")
        match = re.search(r"/Contents (\d+) 0 R", page)
        if not match:
            return []
        contents_obj = self._get_obj(int(match.group(1)))
        raw = self._extract_stream_bytes(contents_obj)
        if raw is None:
            return []
        decoded = zlib.decompress(raw).decode("latin1")

        runs: list[Run] = []
        x = 0.0
        y = 0.0
        for raw_line in decoded.splitlines():
            tm = re.search(r"1 0 0 -1 ([0-9.\-]+) ([0-9.\-]+) Tm", raw_line)
            if tm:
                x = float(tm.group(1))
                y = float(tm.group(2))
            td = re.search(r"([0-9.\-]+) ([0-9.\-]+) Td", raw_line)
            if td:
                x += float(td.group(1))
                y += float(td.group(2))
            if "[" not in raw_line or "TJ" not in raw_line:
                continue
            parts = re.findall(r"<([0-9A-Fa-f]+)>", raw_line)
            if not parts:
                continue
            text = normalize_text("".join(self._decode_hex(part) for part in parts))
            runs.append(Run(x=x, y=y, text=text))
        return runs

    def _extract_stream_bytes(self, obj: bytes) -> bytes | None:
        start = re.search(rb"stream\r?\n", obj)
        length = re.search(rb"/Length (\d+)", obj)
        if not start or not length:
            return None
        data_start = start.end()
        data_end = data_start + int(length.group(1))
        return obj[data_start:data_end]

    def _extract_code_text(self, page_objs: list[int]) -> str:
        all_runs: list[Run] = []
        for page_obj in page_objs:
            all_runs.extend(self._page_runs(page_obj))
        if len(all_runs) < 3:
            return ""

        body_runs = all_runs[2:]
        code_runs = []
        for run in body_runs:
            if run.text.strip():
                code_runs.append(run)

        lines: dict[int, str] = {}
        current_num: int | None = None
        current_segments: list[Run] = []

        def flush() -> None:
            nonlocal current_num, current_segments
            if current_num is None:
                return
            base_x = 62.52
            char_w = 4.32
            out = ""
            for seg in sorted(current_segments, key=lambda r: (round(r.x, 2), r.text)):
                col = max(0, round((seg.x - base_x) / char_w))
                if col > len(out):
                    out += " " * (col - len(out))
                if col < len(out):
                    col = len(out)
                out += seg.text
            lines[current_num] = out.rstrip()
            current_num = None
            current_segments = []

        for run in code_runs:
            stripped = run.text.strip()
            if run.x <= 60.5 and stripped.isdigit():
                flush()
                current_num = int(stripped)
                current_segments = []
                continue
            if current_num is not None:
                current_segments.append(run)
        flush()

        if not lines:
            return ""
        max_line = max(lines)
        ordered = [lines.get(i, "") for i in range(1, max_line + 1)]
        non_empty = [line for line in ordered if line.strip()]
        common_indent = 0
        if non_empty:
            common_indent = min(len(line) - len(line.lstrip(" ")) for line in non_empty)
        if common_indent:
            ordered = [line[common_indent:] if line else "" for line in ordered]
        first_non_empty = next((line for line in ordered if line.strip()), "")
        first_indent = len(first_non_empty) - len(first_non_empty.lstrip(" "))
        if first_indent:
            prefix = " " * first_indent
            ordered = [
                line[first_indent:] if line.startswith(prefix) else line for line in ordered
            ]
        return "\n".join(ordered) + "\n"

    def _extract_markdown_text(self, page_objs: list[int]) -> str:
        blocks: list[str] = []
        for page_obj in page_objs:
            runs = self._page_runs(page_obj)
            if not runs:
                continue
            rows: dict[float, list[Run]] = {}
            for run in runs[2:]:
                if not run.text.strip():
                    continue
                key = round(run.y, 1)
                rows.setdefault(key, []).append(run)
            lines = []
            for key in sorted(rows):
                line = "".join(
                    seg.text for seg in sorted(rows[key], key=lambda seg: seg.x)
                ).rstrip()
                if line:
                    lines.append(line)
            blocks.append("\n".join(lines))
        text = "\n\n".join(blocks)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            text += "\n"
        return text

    def extract(self) -> dict[str, str]:
        entries = self._outline_entries()
        file_entries = [
            (title, page_ref)
            for title, page_ref in entries
            if "/" in title or title in {"pyproject.toml", ".streamlit/config.toml", "README.md"}
        ]
        page_index = {page: idx for idx, page in enumerate(self.page_order)}

        extracted: dict[str, str] = {}
        for idx, (title, page_ref) in enumerate(file_entries):
            start = page_index[page_ref]
            end = (
                page_index[file_entries[idx + 1][1]]
                if idx + 1 < len(file_entries)
                else len(self.page_order)
            )
            page_objs = self.page_order[start:end]
            if title.endswith((".py", ".toml")):
                content = self._extract_code_text(page_objs)
            else:
                content = self._extract_markdown_text(page_objs)
            extracted[title] = content
        return extracted


def main() -> None:
    extractor = PdfRepoExtractor(PDF_PATH)
    files = extractor.extract()
    for rel_path, content in files.items():
        path = ROOT / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
