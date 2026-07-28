from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass(frozen=True)
class Source:
    source_id: str
    filename: str
    title: str
    work: str
    chapter: str
    evidence_kind: str
    content_type: str
    uri: str
    version: str
    text: str


CHINESE_NUMBER = "一二三四五六七八九十百"
HEADING_RE = re.compile(rf"^(?:[{CHINESE_NUMBER}]+、.+|卷[{CHINESE_NUMBER}0-9]+|[○《].+|(?:通神|六亲)论|.+(?:总论|说类))$")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the structured Bazi classics v2 corpus")
    parser.add_argument("--books-root", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("corpora/bazi-theory/v2"),
    )
    args = parser.parse_args()
    output = args.output.resolve()
    sources_dir = output / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    sources = [
        *_build_ziping(args.books_root),
        _pdf_original(
            args.books_root / "穷通宝鉴.pdf",
            source_id="ksrc_bazi_qiongtong_original_v2",
            filename="qiongtong-original.md",
            title="穷通宝鉴：结构化核心原文",
            work="穷通宝鉴",
        ),
        *_build_ditiansui(args.books_root / "滴天髓.pdf"),
        _build_shenfeng(),
        _structured_text(
            args.books_root / "八字 - 渊海子平.txt",
            source_id="ksrc_bazi_yuanhai_original_v2",
            filename="yuanhai-original.md",
            title="渊海子平：结构化核心原文",
            work="渊海子平",
        ),
        _build_sanming(args.books_root / "八字 - 三命通会.txt"),
    ]

    for source in sources:
        (sources_dir / source.filename).write_text(source.text.strip() + "\n", encoding="utf-8")
    manifest = _manifest(sources, sources_dir)
    (output / "manifest.toml").write_text(manifest, encoding="utf-8")
    (output / "replacement-matrix.json").write_text(
        json.dumps(_replacement_matrix(sources), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _build_ziping(root: Path) -> list[Source]:
    path = root / "《子平真诠》本义(完整版).doc"
    text = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    original: list[str] = ["# 子平真诠：古籍原文"]
    commentary: list[str] = ["# 子平真诠：现代解读"]
    cases: list[str] = ["# 子平真诠：命例材料"]
    chapter = "总论"
    mode = ""
    for raw in text.splitlines():
        line = _clean_line(raw)
        if not line:
            continue
        if re.match(rf"^[{CHINESE_NUMBER}]+、", line):
            chapter = line
            original.extend(["", f"## {chapter}"])
            commentary.extend(["", f"## {chapter}"])
            cases.extend(["", f"## {chapter}"])
            mode = ""
            continue
        if line.startswith("原文："):
            mode = "original"
            original.extend(["", line.removeprefix("原文：").strip()])
            continue
        if line.startswith("解读："):
            mode = "commentary"
            value = line.removeprefix("解读：").strip()
            if value:
                commentary.extend(["", value])
            continue
        if _looks_like_case(line):
            mode = "case"
        if mode == "original":
            original.append(line)
        elif mode == "commentary":
            commentary.append(line)
        elif mode == "case":
            cases.append(line)
    uri = path.resolve().as_uri()
    return [
        Source("ksrc_bazi_ziping_original_v2", "ziping-original.md", "子平真诠：结构化原文", "子平真诠", "全书核心篇章", "classical_original", "classical_original", f"{uri}#classical-original", "user-file-structured-v2", "\n".join(original)),
        Source("ksrc_bazi_ziping_modern_v2", "ziping-modern-commentary.md", "子平真诠：现代解读", "子平真诠", "全书核心篇章", "modern_commentary", "modern_commentary", f"{uri}#modern-commentary", "user-file-structured-v2", "\n".join(commentary)),
        Source("ksrc_bazi_ziping_cases_v2", "ziping-cases.md", "子平真诠：命例材料", "子平真诠", "全书命例", "case_record", "case_record", f"{uri}#case-record", "user-file-structured-v2", "\n".join(cases)),
    ]


def _pdf_original(path: Path, *, source_id: str, filename: str, title: str, work: str) -> Source:
    text = _extract_pdf(path)
    markdown = _to_markdown(work, text)
    if work == "穷通宝鉴":
        markdown = re.sub(
            rf"(?<!# )((?:三春|三夏|三秋|三冬)[甲乙丙丁戊己庚辛壬癸][木火土金水]?(?:总论)?)",
            r"\n\n## \1\n\n",
            markdown,
        )
    return Source(source_id, filename, title, work, "全书核心篇章", "classical_original", "classical_original", path.resolve().as_uri(), "user-file-extracted-v2", markdown)


def _build_ditiansui(path: Path) -> list[Source]:
    text = _extract_pdf(path)
    original: list[str] = ["# 滴天髓：原文"]
    commentary: list[str] = ["# 滴天髓：原注"]
    current_heading = "通神论"
    for section_heading, body in _sections(text):
        if section_heading:
            current_heading = section_heading
        compact = _join_wrapped_lines(body)
        if not compact:
            continue
        note_match = re.search(r"原注[：，,；;]", compact)
        ren_match = re.search(r"任氏曰[：，,；;]", compact)
        first_note = note_match.start() if note_match else -1
        first_ren = ren_match.start() if ren_match else -1
        end_original = min([index for index in (first_note, first_ren) if index >= 0], default=len(compact))
        verse = compact[:end_original].strip()
        if verse and len(verse) <= 240:
            original.extend(["", f"## {current_heading}", "", verse])
        if first_note >= 0:
            end_note = first_ren if first_ren > first_note else len(compact)
            note = compact[note_match.end() : end_note].strip() if note_match else ""
            if note:
                commentary.extend(["", f"## {current_heading}", "", note])
    uri = path.resolve().as_uri()
    return [
        Source("ksrc_bazi_ditiansui_original_v2", "ditiansui-original.md", "滴天髓：结构化原文", "滴天髓", "通神论；六亲论", "classical_original", "classical_original", f"{uri}#classical-original", "user-file-extracted-v2", "\n".join(original)),
        Source("ksrc_bazi_ditiansui_commentary_v2", "ditiansui-original-commentary.md", "滴天髓：原注", "滴天髓", "通神论；六亲论", "historical_commentary", "historical_commentary", f"{uri}#historical-commentary", "user-file-extracted-v2", "\n".join(commentary)),
    ]


def _build_shenfeng() -> Source:
    params = urllib.parse.urlencode({"action": "query", "prop": "extracts", "revids": "1378606", "explaintext": "1", "format": "json", "formatversion": "2"})
    request = urllib.request.Request(
        f"https://zh.wikisource.org/w/api.php?{params}",
        headers={"User-Agent": "MartenRuntimeKnowledgeCorpus/1.0 (local research)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        payload = json.load(response)
    text = payload["query"]["pages"][0]["extract"]
    wanted = ("病药", "雕枯", "旺弱", "损益", "生长", "格局", "动静", "盖头", "六亲")
    selected: list[str] = ["# 神峰通考：核心理论原文"]
    for heading, body in _sections(text):
        if heading and any(term in heading for term in wanted):
            selected.extend(["", f"## {heading}", "", _join_wrapped_lines(body)])
    return Source(
        "ksrc_bazi_shenfeng_original_v2",
        "shenfeng-original.md",
        "神峰通考：结构化核心原文",
        "神峰通考",
        "病药、旺弱、损益等核心篇章",
        "classical_original",
        "classical_original",
        "https://zh.wikisource.org/w/index.php?title=神峰通考&oldid=1378606",
        "wikisource-oldid-1378606-structured-v2",
        "\n".join(selected),
    )


def _structured_text(path: Path, *, source_id: str, filename: str, title: str, work: str) -> Source:
    text = path.read_text(encoding="utf-8-sig")
    return Source(source_id, filename, title, work, "核心理论篇章", "classical_original", "classical_original", path.resolve().as_uri(), "user-file-structured-v2", _to_markdown(work, text))


def _build_sanming(path: Path) -> Source:
    text = path.read_text(encoding="utf-8-sig").replace("必??滞", "必滞")
    wanted = ("印食官财名义", "正官", "偏官", "官煞混杂", "从煞", "正财", "偏财", "印绶", "食神", "伤官", "建禄", "羊刃", "阳刃", "杂气", "格局", "看命口诀")
    selected: list[str] = ["# 三命通会：核心理论原文"]
    for heading, body in _sections(text):
        if heading and any(term in heading for term in wanted):
            selected.extend(["", f"## {heading}", "", _join_wrapped_lines(body)])
    return Source("ksrc_bazi_sanming_original_v2", "sanming-original.md", "三命通会：结构化核心原文", "三命通会", "格局与十神核心篇章", "classical_original", "classical_original", path.resolve().as_uri(), "user-file-structured-v2", "\n".join(selected))


def _extract_pdf(path: Path) -> str:
    return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)


def _to_markdown(work: str, text: str) -> str:
    output = [f"# {work}：结构化原文"]
    for heading, body in _sections(text):
        if heading:
            output.extend(["", f"## {heading}"])
        normalized = _join_wrapped_lines(body)
        if normalized:
            output.extend(["", normalized])
    return "\n".join(output)


def _sections(text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    heading = ""
    body: list[str] = []
    for raw in text.splitlines():
        line = _clean_line(raw)
        if not line:
            continue
        if _is_heading(line):
            if body:
                sections.append((heading, body))
            heading, body = _normalize_heading(line), []
        else:
            body.append(line)
    if body:
        sections.append((heading, body))
    return sections


def _is_heading(line: str) -> bool:
    return len(line) <= 48 and bool(HEADING_RE.fullmatch(line))


def _normalize_heading(line: str) -> str:
    return re.sub(r"[《》○]", "", re.sub(r"\s+", "", line)).strip()


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.replace("\ufeff", "").replace("\u2028", " ")).strip()


def _join_wrapped_lines(lines: list[str]) -> str:
    return "".join(_clean_line(line) for line in lines if _clean_line(line))


def _looks_like_case(line: str) -> bool:
    return any(token in line for token in ("命式为", "命造：", "大运：", "男命式", "女命式"))


def _manifest(sources: list[Source], sources_dir: Path) -> str:
    rows = [
        'schema_version = "knowledge.corpus.v1"',
        'release_id = "bazi-theory-classics-structured-v2"',
        'namespace = "bazi-theory"',
        'description = "Structured core theory from six trusted classics, with original, commentary and case evidence separated."',
        "",
        "[release_metadata]",
        'completeness = "structured_core_chapters"',
        'language = "zh-Hans-and-zh-Hant"',
        'corpus_layer = "classical_books"',
        'prepared_at = "2026-07-28"',
        f"source_count = {len(sources)}",
        "",
        "[governance]",
        'corpus_owner = "repository owner"',
        'reviewer = "repository owner"',
        'release_approver = "repository owner"',
        'approval_status = "reviewed_baseline"',
    ]
    for source in sources:
        digest = hashlib.sha256((sources_dir / source.filename).read_bytes()).hexdigest()
        rows.extend(
            [
                "",
                "[[sources]]",
                f'source_id = "{source.source_id}"',
                f'file = "sources/{source.filename}"',
                f'title = "{source.title}"',
                'kind = "markdown"',
                f'uri = "{source.uri}"',
                f'version = "{source.version}"',
                f'sha256 = "{digest}"',
                "",
                "[sources.metadata]",
                'corpus_type = "theory"',
                'review_status = "reviewed"',
                'license = "trusted user-provided or fixed transcription; not re-evaluated"',
                'provenance = "trusted input; extraction and structure checked for retrieval"',
                'calculation_scope = "theory_interpretation"',
                f'content_type = "{source.content_type}"',
                f'evidence_kind = "{source.evidence_kind}"',
                f'work = "{source.work}"',
                f'chapter = "{source.chapter}"',
                'edition_or_source = "trusted supplied text or fixed transcription"',
                f'source_url = "{source.uri}"',
                'verification_status = "trusted_input_structure_checked"',
                'school = "ziping"',
                'method = "classical_theory"',
            ]
        )
    return "\n".join(rows) + "\n"


def _replacement_matrix(sources: list[Source]) -> dict[str, object]:
    replacements = {
        "ksrc_bazi_classics_qiongtong_v1": ["ksrc_bazi_qiongtong_original_v2"],
        "ksrc_bazi_classics_ditiansui_v1": ["ksrc_bazi_ditiansui_original_v2", "ksrc_bazi_ditiansui_commentary_v2"],
        "ksrc_bazi_classics_shenfeng_v1": ["ksrc_bazi_shenfeng_original_v2"],
        "ksrc_bazi_classics_yuanhai_v1": ["ksrc_bazi_yuanhai_original_v2"],
        "ksrc_bazi_classics_ziping_v1": ["ksrc_bazi_ziping_original_v2", "ksrc_bazi_ziping_modern_v2"],
        "ksrc_bazi_classics_sanming_v1": ["ksrc_bazi_sanming_original_v2"],
        "ksrc_localtest_ziping_benyi_full": ["ksrc_bazi_ziping_original_v2", "ksrc_bazi_ziping_modern_v2", "ksrc_bazi_ziping_cases_v2"],
    }
    return {"schema_version": "knowledge.corpus.replacement.v1", "release_id": "bazi-theory-classics-structured-v2", "replacements": replacements, "new_source_ids": [source.source_id for source in sources]}


if __name__ == "__main__":
    main()
