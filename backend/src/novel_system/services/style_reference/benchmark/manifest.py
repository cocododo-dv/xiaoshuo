"""风格基准清单与公私语料边界。

公开清单可用于准备训练语料和生成任务；隐藏清单必须只在评分进程中读取。
留出单位是完整作品，禁止把同一作品的相邻段落随机拆到训练/测试两侧。
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


STYLE_BENCHMARK_SCHEMA_VERSION = 1
_WORK_HEADING = re.compile(r"^《([^》\r\n]{1,120})》\s*$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,80}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_PUBLIC_FORBIDDEN_KEYS = frozenset(
    {
        "holdoutworks",
        "hiddenworks",
        "privaterubric",
        "referenceanswer",
        "expectedanswer",
    }
)


class StyleBenchmarkError(ValueError):
    """清单、结果矩阵或评分输入不可信。"""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CorpusWork:
    title: str
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def checksum(self) -> str:
        return hash_text(self.text)


@dataclass(frozen=True, slots=True)
class BenchmarkAuthor:
    author_id: str
    label: str
    source_path: Path
    source_text_checksum: str
    train_works: tuple[CorpusWork, ...]
    rights: str

    @property
    def training_text(self) -> str:
        return "\n\n".join(
            f"《{work.title}》\n\n{work.text}" for work in self.train_works
        )

    @property
    def anonymous_training_text(self) -> str:
        """保留作品边界但移除可被模型直接利用的作者/篇名提示。"""

        return "\n\n".join(
            f"《参考作品{index:02d}》\n\n{work.text}"
            for index, work in enumerate(self.train_works, start=1)
        )

    @property
    def anonymous_corpus_id(self) -> str:
        return f"corpus_{self.training_checksum[:12]}"

    @property
    def training_checksum(self) -> str:
        return hash_json(
            [
                {"title": work.title, "checksum": work.checksum}
                for work in self.train_works
            ]
        )


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    title: str
    genre: str
    scene_function: str
    prompt: str
    required_term_groups: tuple[tuple[str, ...], ...]
    min_chars: int
    max_chars: int

    def public_payload(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "title": self.title,
            "genre": self.genre,
            "scene_function": self.scene_function,
            "prompt": self.prompt,
            "required_term_groups": [
                list(group) for group in self.required_term_groups
            ],
            "min_chars": self.min_chars,
            "max_chars": self.max_chars,
        }


@dataclass(frozen=True, slots=True)
class StyleBenchmarkManifest:
    benchmark_id: str
    manifest_version: str
    isolation_mode: str
    authors: tuple[BenchmarkAuthor, ...]
    cases: tuple[BenchmarkCase, ...]
    public_manifest_hash: str
    source_payload: dict[str, Any]

    @property
    def author_ids(self) -> tuple[str, ...]:
        return tuple(author.author_id for author in self.authors)

    def author_for(self, author_id: str) -> BenchmarkAuthor:
        for author in self.authors:
            if author.author_id == author_id:
                return author
        raise StyleBenchmarkError(f"未知基准作者: {author_id}")

    def case_for(self, case_id: str) -> BenchmarkCase:
        for case in self.cases:
            if case.case_id == case_id:
                return case
        raise StyleBenchmarkError(f"未知基准场景: {case_id}")

    def public_summary(self) -> dict[str, Any]:
        return {
            "schema_version": STYLE_BENCHMARK_SCHEMA_VERSION,
            "benchmark_id": self.benchmark_id,
            "manifest_version": self.manifest_version,
            "isolation_mode": self.isolation_mode,
            "public_manifest_hash": self.public_manifest_hash,
            "author_count": len(self.authors),
            "case_count": len(self.cases),
            "authors": [
                {
                    "author_id": author.author_id,
                    "label": author.label,
                    "train_work_count": len(author.train_works),
                    "train_char_count": sum(
                        work.char_count for work in author.train_works
                    ),
                    "training_checksum": author.training_checksum,
                    "source_text_checksum": author.source_text_checksum,
                    "rights": author.rights,
                }
                for author in self.authors
            ],
            "expected_generation_count": len(self.cases) * (1 + len(self.authors)),
        }


@dataclass(frozen=True, slots=True)
class HiddenAuthorCorpus:
    author_id: str
    holdout_works: tuple[CorpusWork, ...]

    @property
    def checksum(self) -> str:
        return hash_json(
            [
                {"title": work.title, "checksum": work.checksum}
                for work in self.holdout_works
            ]
        )


@dataclass(frozen=True, slots=True)
class StyleBenchmarkBundle:
    public: StyleBenchmarkManifest
    hidden_authors: tuple[HiddenAuthorCorpus, ...]
    private_manifest_hash: str
    benchmark_manifest_hash: str

    def hidden_for(self, author_id: str) -> HiddenAuthorCorpus:
        for author in self.hidden_authors:
            if author.author_id == author_id:
                return author
        raise StyleBenchmarkError(f"隐藏语料缺少作者: {author_id}")

    def safe_summary(self) -> dict[str, Any]:
        summary = self.public.public_summary()
        summary.update(
            {
                "private_manifest_hash": self.private_manifest_hash,
                "benchmark_manifest_hash": self.benchmark_manifest_hash,
                "hidden": [
                    {
                        "author_id": author.author_id,
                        "holdout_work_count": len(author.holdout_works),
                        "holdout_char_count": sum(
                            work.char_count for work in author.holdout_works
                        ),
                        "holdout_checksum": author.checksum,
                    }
                    for author in self.hidden_authors
                ],
            }
        )
        return summary


def parse_titled_works(text: str) -> dict[str, CorpusWork]:
    """解析以独占行 ``《篇名》`` 分隔的公版合集。"""

    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    headings: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = _WORK_HEADING.fullmatch(line.strip())
        if match:
            headings.append((index, match.group(1).strip()))
    if not headings:
        raise StyleBenchmarkError("语料没有独占行作品标题（格式应为《篇名》）")
    if any(line.strip() for line in lines[: headings[0][0]]):
        raise StyleBenchmarkError("首个作品标题前存在未归属正文")

    works: dict[str, CorpusWork] = {}
    for position, (line_index, title) in enumerate(headings):
        if not title or title in works:
            raise StyleBenchmarkError(f"语料作品标题为空或重复: {title!r}")
        next_index = (
            headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        )
        body = "\n".join(lines[line_index + 1 : next_index]).strip()
        if not body:
            raise StyleBenchmarkError(f"作品正文为空: {title}")
        works[title] = CorpusWork(title=title, text=body)
    return works


def load_style_benchmark_manifest(
    source: str | Path | Mapping[str, Any],
    *,
    workspace_root: str | Path | None = None,
) -> StyleBenchmarkManifest:
    payload, source_dir = _load_json_payload(source, label="公开清单")
    _assert_no_private_keys(payload)
    _require_schema(payload)
    benchmark_id = _identifier(payload.get("benchmark_id"), "benchmark_id")
    manifest_version = _nonempty(payload.get("manifest_version"), "manifest_version")
    isolation_mode = _nonempty(payload.get("isolation_mode"), "isolation_mode")
    if isolation_mode != "work_level_holdout":
        raise StyleBenchmarkError("isolation_mode 必须是 work_level_holdout")

    root = (
        Path(workspace_root).resolve()
        if workspace_root is not None
        else _workspace_root()
    )
    raw_authors = payload.get("authors")
    if not isinstance(raw_authors, list) or len(raw_authors) < 2:
        raise StyleBenchmarkError("公开清单至少需要两个对照作者")
    authors: list[BenchmarkAuthor] = []
    seen_authors: set[str] = set()
    for index, raw in enumerate(raw_authors):
        if not isinstance(raw, Mapping):
            raise StyleBenchmarkError(f"authors[{index}] 必须是对象")
        author_id = _identifier(raw.get("author_id"), f"authors[{index}].author_id")
        if author_id in seen_authors:
            raise StyleBenchmarkError(f"作者 id 重复: {author_id}")
        seen_authors.add(author_id)
        source_path = _resolve_source_path(
            raw.get("source_path"), root=root, source_dir=source_dir
        )
        source_text = _read_text(source_path)
        source_text_checksum = hash_text(
            source_text.replace("\r\n", "\n").replace("\r", "\n")
        )
        expected_source_checksum = _nonempty(
            raw.get("source_text_sha256"),
            f"authors[{index}].source_text_sha256",
        ).lower()
        if not _SHA256.fullmatch(expected_source_checksum):
            raise StyleBenchmarkError(
                f"authors[{index}].source_text_sha256 必须是 64 位十六进制"
            )
        if source_text_checksum != expected_source_checksum:
            raise StyleBenchmarkError(
                f"作者 {author_id} 的语料文件与冻结 source_text_sha256 不一致"
            )
        all_works = parse_titled_works(source_text)
        train_titles = _unique_text_list(
            raw.get("train_works"), f"authors[{index}].train_works"
        )
        missing = [title for title in train_titles if title not in all_works]
        if missing:
            raise StyleBenchmarkError(f"作者 {author_id} 的训练作品不存在: {missing}")
        rights = _nonempty(raw.get("rights"), f"authors[{index}].rights")
        if "公有领域" not in rights and "public domain" not in rights.lower():
            raise StyleBenchmarkError(f"作者 {author_id} 未明确声明公有领域语料")
        authors.append(
            BenchmarkAuthor(
                author_id=author_id,
                label=_nonempty(raw.get("label"), f"authors[{index}].label"),
                source_path=source_path,
                source_text_checksum=source_text_checksum,
                train_works=tuple(all_works[title] for title in train_titles),
                rights=rights,
            )
        )

    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise StyleBenchmarkError("公开清单必须包含非空 cases")
    cases: list[BenchmarkCase] = []
    seen_cases: set[str] = set()
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, Mapping):
            raise StyleBenchmarkError(f"cases[{index}] 必须是对象")
        case_id = _identifier(raw.get("case_id"), f"cases[{index}].case_id")
        if case_id in seen_cases:
            raise StyleBenchmarkError(f"场景 id 重复: {case_id}")
        seen_cases.add(case_id)
        groups = _term_groups(
            raw.get("required_term_groups"), f"cases[{index}].required_term_groups"
        )
        min_chars = _positive_int(raw.get("min_chars"), f"cases[{index}].min_chars")
        max_chars = _positive_int(raw.get("max_chars"), f"cases[{index}].max_chars")
        if max_chars < min_chars:
            raise StyleBenchmarkError(f"场景 {case_id} 的长度范围无效")
        cases.append(
            BenchmarkCase(
                case_id=case_id,
                title=_nonempty(raw.get("title"), f"cases[{index}].title"),
                genre=_nonempty(raw.get("genre"), f"cases[{index}].genre"),
                scene_function=_nonempty(
                    raw.get("scene_function"), f"cases[{index}].scene_function"
                ),
                prompt=_nonempty(raw.get("prompt"), f"cases[{index}].prompt"),
                required_term_groups=groups,
                min_chars=min_chars,
                max_chars=max_chars,
            )
        )

    # 结果必须同时冻结清单和实际公开训练正文。只哈希 JSON 会允许语料文件在
    # 路径不变时被替换，而旧 checkpoint 仍被误认成同一轮基准。
    public_manifest_hash = hash_json(
        {
            "manifest": payload,
            "training_corpus_checksums": {
                author.author_id: author.training_checksum for author in authors
            },
        }
    )
    return StyleBenchmarkManifest(
        benchmark_id=benchmark_id,
        manifest_version=manifest_version,
        isolation_mode=isolation_mode,
        authors=tuple(authors),
        cases=tuple(cases),
        public_manifest_hash=public_manifest_hash,
        source_payload=deepcopy(payload),
    )


def load_style_benchmark(
    public_source: str | Path | Mapping[str, Any],
    private_source: str | Path | Mapping[str, Any],
    *,
    workspace_root: str | Path | None = None,
) -> StyleBenchmarkBundle:
    """评分侧入口。生成侧不得调用；应只加载公开清单。"""

    public = load_style_benchmark_manifest(public_source, workspace_root=workspace_root)
    private, _ = _load_json_payload(private_source, label="隐藏清单")
    _require_schema(private)
    if private.get("benchmark_id") != public.benchmark_id:
        raise StyleBenchmarkError("公开/隐藏清单 benchmark_id 不一致")
    if private.get("manifest_version") != public.manifest_version:
        raise StyleBenchmarkError("公开/隐藏清单 manifest_version 不一致")
    raw_authors = private.get("authors")
    if not isinstance(raw_authors, list):
        raise StyleBenchmarkError("隐藏清单 authors 必须是列表")
    private_by_id: dict[str, Mapping[str, Any]] = {}
    for raw in raw_authors:
        if not isinstance(raw, Mapping):
            raise StyleBenchmarkError("隐藏清单作者项必须是对象")
        author_id = _identifier(raw.get("author_id"), "hidden.authors.author_id")
        if author_id in private_by_id:
            raise StyleBenchmarkError(f"隐藏清单作者重复: {author_id}")
        private_by_id[author_id] = raw
    if set(private_by_id) != set(public.author_ids):
        raise StyleBenchmarkError("公开/隐藏清单作者集合不一致")

    hidden_authors: list[HiddenAuthorCorpus] = []
    for author in public.authors:
        raw = private_by_id[author.author_id]
        titles = _unique_text_list(
            raw.get("holdout_works"), f"hidden.{author.author_id}.holdout_works"
        )
        train_titles = {work.title for work in author.train_works}
        overlap = sorted(train_titles.intersection(titles))
        if overlap:
            raise StyleBenchmarkError(
                f"作者 {author.author_id} 训练/隐藏作品重叠: {overlap}"
            )
        all_works = parse_titled_works(_read_text(author.source_path))
        missing = [title for title in titles if title not in all_works]
        if missing:
            raise StyleBenchmarkError(
                f"作者 {author.author_id} 的隐藏作品不存在: {missing}"
            )
        hidden_authors.append(
            HiddenAuthorCorpus(
                author_id=author.author_id,
                holdout_works=tuple(all_works[title] for title in titles),
            )
        )

    private_hash = hash_json(private)
    return StyleBenchmarkBundle(
        public=public,
        hidden_authors=tuple(hidden_authors),
        private_manifest_hash=private_hash,
        benchmark_manifest_hash=hash_json(
            {
                "schema_version": STYLE_BENCHMARK_SCHEMA_VERSION,
                "public_manifest_hash": public.public_manifest_hash,
                "private_manifest_hash": private_hash,
                "hidden_corpus_checksums": {
                    author.author_id: author.checksum for author in hidden_authors
                },
            }
        ),
    )


def _load_json_payload(
    source: str | Path | Mapping[str, Any], *, label: str
) -> tuple[dict[str, Any], Path | None]:
    if isinstance(source, Mapping):
        return deepcopy(dict(source)), None
    path = Path(source).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StyleBenchmarkError(f"{label}不可读或不是合法 JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise StyleBenchmarkError(f"{label}根节点必须是对象")
    return payload, path.parent


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise StyleBenchmarkError(f"语料不可读（要求 UTF-8）: {path}") from exc


def _resolve_source_path(value: Any, *, root: Path, source_dir: Path | None) -> Path:
    raw = _nonempty(value, "source_path")
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    rooted = (root / candidate).resolve()
    if rooted.exists() or source_dir is None:
        return rooted
    return (source_dir / candidate).resolve()


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[6]


def _require_schema(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != STYLE_BENCHMARK_SCHEMA_VERSION:
        raise StyleBenchmarkError("style benchmark schema_version 必须是 1")


def _assert_no_private_keys(value: Any, *, path: str = "public") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in _PUBLIC_FORBIDDEN_KEYS:
                raise StyleBenchmarkError(f"公开清单禁止包含隐藏字段: {path}.{key}")
            _assert_no_private_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_private_keys(item, path=f"{path}[{index}]")


def _identifier(value: Any, field: str) -> str:
    text = _nonempty(value, field).lower()
    if not _IDENTIFIER.fullmatch(text):
        raise StyleBenchmarkError(f"{field} 不是合法标识符")
    return text


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StyleBenchmarkError(f"{field} 必须是非空字符串")
    return value.strip()


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StyleBenchmarkError(f"{field} 必须是正整数")
    return value


def _unique_text_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise StyleBenchmarkError(f"{field} 必须是非空字符串列表")
    values = tuple(_nonempty(item, field) for item in value)
    if len(values) != len(set(values)):
        raise StyleBenchmarkError(f"{field} 存在重复项")
    return values


def _term_groups(value: Any, field: str) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list) or not value:
        raise StyleBenchmarkError(f"{field} 必须是非空二维字符串列表")
    return tuple(
        _unique_text_list(group, f"{field}[{index}]")
        for index, group in enumerate(value)
    )
