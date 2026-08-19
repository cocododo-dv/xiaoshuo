# -*- coding: utf-8 -*-
"""从维基文库固定 revision 生成朱自清 benchmark 专用公版语料。

默认只打印摘要（下载缓存写入被 Git 忽略的 benchmark 工作区）；传
``--write`` 才会原子更新 corpus 文件。页面 revision 固定，避免上游页面
后续编辑导致同一仓库版本的基准漂移。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen


OUTPUT = Path(__file__).resolve().parent / "corpus" / "zhuziqing_benchmark_essays.txt"
CACHE_DIR = (
    Path(__file__).resolve().parents[3] / ".style-benchmark" / "wikisource-cache"
)
USER_AGENT = "NovelSystemStyleBenchmark/1.0 (public-domain corpus reproducibility)"
_INVISIBLE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_SPACE = re.compile(r"[ \t\xa0]+")


@dataclass(frozen=True, slots=True)
class SourcePage:
    title: str
    source_title: str
    revision: int


SOURCES = (
    SourcePage("背影", "背影", 2570094),
    SourcePage("荷塘月色", "荷塘月色", 2570152),
    SourcePage("温州的踪迹", "溫州的蹤跡", 2588575),
    SourcePage("航船中的文明", "航船中的文明", 2551015),
    SourcePage("匆匆", "匆匆", 2570968),
    SourcePage("歌声", "歌聲", 2570953),
    SourcePage("桨声灯影里的秦淮河", "槳聲燈影裏的秦淮河", 2371866),
    SourcePage("女人", "女人", 2636154),
    SourcePage("白种人——上帝的骄子", "白種人——上帝的驕子", 2551024),
    SourcePage("阿河", "阿河", 2634172),
    SourcePage("白采", "白采", 2570935),
    SourcePage("一封信", "一封信", 2570939),
    SourcePage("儿女", "儿女", 2571645),
    SourcePage("旅行杂记", "旅行雜記", 2571722),
    SourcePage("说梦", "說夢", 2011663),
    SourcePage("海行杂记", "海行雜記", 2551022),
)

COLLECTIONS = {
    "踪迹": {
        "year": 1924,
        "titles": frozenset(
            {"温州的踪迹", "航船中的文明", "匆匆", "歌声", "桨声灯影里的秦淮河"}
        ),
    },
    "背影": {
        "year": 1928,
        "titles": frozenset(
            {
                "背影",
                "荷塘月色",
                "女人",
                "白种人——上帝的骄子",
                "阿河",
                "白采",
                "一封信",
                "儿女",
                "旅行杂记",
                "说梦",
                "海行杂记",
            }
        ),
    },
}


class _ParagraphParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self._depth = 0
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag == "p":
            self._depth += 1
            if self._depth == 1:
                self._parts = []
        elif self._depth and tag in {"sup", "style", "script"}:
            self._ignored_depth += 1
        elif self._depth and tag == "br" and not self._ignored_depth:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._depth and tag in {"sup", "style", "script"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag == "p" and self._depth:
            self._depth -= 1
            if self._depth == 0:
                text = _clean_text("".join(self._parts))
                if text and not _is_site_noise(text):
                    self.paragraphs.append(text)

    def handle_data(self, data: str) -> None:
        if self._depth and not self._ignored_depth:
            self._parts.append(data)


def _clean_text(text: str) -> str:
    lines = []
    for raw_line in _INVISIBLE.sub("", text).splitlines():
        line = _SPACE.sub(" ", raw_line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _is_site_noise(text: str) -> bool:
    normalized = text.casefold()
    return (
        "属于公有领域" in text
        or "版权期限" in text
        or normalized.startswith("public domain")
        or "creative commons" in normalized
    )


def _fetch(page: SourcePage) -> tuple[str, str]:
    cache_path = CACHE_DIR / f"{page.revision}.html"
    if cache_path.exists():
        raw = cache_path.read_bytes()
    else:
        raw = _fetch_remote(page)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(".html.tmp")
        temporary.write_bytes(raw)
        temporary.replace(cache_path)
    parser = _ParagraphParser()
    parser.feed(raw.decode("utf-8"))
    body = "\n\n".join(parser.paragraphs).strip()
    if len(body) < 300:
        raise RuntimeError(f"{page.title} 提取正文过短: {len(body)}")
    if "Wikisource" in body or "维基文库" in body:
        raise RuntimeError(f"{page.title} 正文混入站点导航")
    return body, hashlib.sha256(raw).hexdigest()


def _fetch_remote(page: SourcePage) -> bytes:
    encoded_title = quote(page.source_title, safe="")
    url = (
        "https://zh.wikisource.org/api/rest_v1/page/html/"
        f"{encoded_title}/{page.revision}"
    )
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-hans"},
    )
    raw: bytes | None = None
    for attempt in range(5):
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310
                raw = response.read()
            break
        except HTTPError as exc:
            if exc.code != 429 or attempt == 4:
                raise RuntimeError(
                    f"抓取 {page.title} revision={page.revision} 失败: HTTP {exc.code}"
                ) from exc
            retry_after = exc.headers.get("Retry-After")
            delay = (
                min(30.0, float(retry_after)) if retry_after else 10.0 + 5.0 * attempt
            )
            time.sleep(max(0.5, delay))
    if raw is None:  # pragma: no cover - 循环失败会在上方抛错
        raise RuntimeError(f"抓取 {page.title} 未返回正文")
    time.sleep(1.25)
    return raw


def _render() -> tuple[str, list[dict[str, object]]]:
    works: list[str] = []
    audit: list[dict[str, object]] = []
    for page in SOURCES:
        collection, collection_year = _collection_for(page.title)
        if collection_year > 1930:
            raise RuntimeError(f"{page.title} 超出 1930 年及以前的全球稳妥公版边界")
        body, html_sha256 = _fetch(page)
        print(
            f"fetched {page.title} revision={page.revision} chars={len(body)}",
            file=sys.stderr,
            flush=True,
        )
        works.append(f"《{page.title}》\n\n{body}")
        audit.append(
            {
                "title": page.title,
                "source_title": page.source_title,
                "revision": page.revision,
                "collection": collection,
                "collection_year": collection_year,
                "char_count": len(body),
                "html_sha256": html_sha256,
            }
        )
    return "\n\n".join(works).strip() + "\n", audit


def _collection_for(title: str) -> tuple[str, int]:
    for collection, metadata in COLLECTIONS.items():
        if title in metadata["titles"]:
            return collection, int(metadata["year"])
    raise RuntimeError(f"{title} 没有冻结的生前出版集来源")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    content, audit = _render()
    if args.write:
        temporary = OUTPUT.with_suffix(f"{OUTPUT.suffix}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(OUTPUT)
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "written": args.write,
                "work_count": len(audit),
                "total_chars": sum(int(row["char_count"]) for row in audit),
                "corpus_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "sources": audit,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
