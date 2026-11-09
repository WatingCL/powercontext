"""单元测试：不依赖 PowerContext 服务，`python -m unittest` 直接跑。

    cd qoder/litcontext && python -m unittest discover -s tests -v
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from litcontext import memory, report, synonyms  # noqa: E402
from litcontext.index import Index  # noqa: E402
from litcontext.parser import parse_file  # noqa: E402
from litcontext.text import highlight_snippet, tokenize  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


class TokenizeTest(unittest.TestCase):
    def test_english_and_chinese(self) -> None:
        tokens = tokenize("GLR 事件检测 threshold")
        self.assertIn("glr", tokens)
        self.assertIn("事件", tokens)
        self.assertIn("threshold", tokens)
        self.assertNotIn("的", tokens)

    def test_snippet_centers_on_hit(self) -> None:
        text = "前缀" * 200 + "广义似然比" + "后缀" * 200
        snippet = highlight_snippet(text, "广义似然比", width=60)
        self.assertIn("广义似然比", snippet)
        self.assertLess(len(snippet), 80)


class ParserTest(unittest.TestCase):
    def test_front_matter_and_sections(self) -> None:
        paper = parse_file(SAMPLES / "03-anderson-2012-glr.md")
        self.assertEqual(paper.paper_id, "p-anderson12")
        self.assertEqual(paper.meta["year"], "2012")
        sections = {p.section for p in paper.passages}
        self.assertIn("方法", sections)
        self.assertGreater(len(paper.passages), 3)

    def test_unsupported_suffix(self) -> None:
        with self.assertRaises(ValueError):
            parse_file(Path("x.docx"))


def make_minimal_pdf(path: Path, lines: List[str]) -> None:
    """手写一个最小合法 PDF（Helvetica + WinAnsi），用于测试 PDF 解析分支。

    不引 reportlab：这里只需要"能有文字层"的 PDF，不是排版。
    """
    content = "BT /F1 11 Tf 60 740 Td 16 TL\n" + "\n".join(
        "(" + line.replace("(", r"\(").replace(")", r"\)") + ") Tj T*" for line in lines
    ) + "\nET"
    body = content.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    path.write_bytes(bytes(out))


class PdfTest(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "需要 pypdf：pip install pypdf")
    def test_pdf_import_and_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            make_minimal_pdf(path, [
                "Event Detection for Non-Intrusive Load Monitoring.",
                "GLR maintains two sliding windows and computes a log-likelihood ratio.",
                "A fixed threshold baseline needs per-house calibration.",
            ])
            paper = parse_file(path)
            self.assertGreaterEqual(len(paper.passages), 1)
            self.assertIn("GLR", " ".join(p.text for p in paper.passages))

            index = Index(Path(tmp) / "t.sqlite3")
            try:
                index.import_file(path)
                hits = index.search("log-likelihood ratio", top_k=1)
                self.assertTrue(hits)
                self.assertIn("likelihood", hits[0].text)
            finally:
                index.close()


    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "需要 pypdf：pip install pypdf")
    def test_textless_pdf_is_rejected(self) -> None:
        # 扫描件（只有图、没有文字层）必须明确报错，而不是静默写入空文档
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scan.pdf"
            make_minimal_pdf(path, [])
            with self.assertRaises(ValueError):
                parse_file(path)


class SynonymTest(unittest.TestCase):
    def test_cross_language_expansion(self) -> None:
        weights = synonyms.expand(["false", "alarm"])
        self.assertIn("误报", weights)
        self.assertEqual(weights["false"], 1.0)
        self.assertLess(weights["误报"], 1.0)  # 扩展词权重必须低于原词

    def test_multi_char_surface_is_tokenized(self) -> None:
        # "广义似然比" 必须拆成中文二元组，否则和索引里的 token 对不上
        weights = synonyms.expand(["glr"])
        self.assertIn("广义", weights)
        self.assertIn("似然", weights)

    def test_expansion_is_capped(self) -> None:
        weights = synonyms.expand(["事件"])
        self.assertLessEqual(len(weights), 1 + synonyms.MAX_PER_TOKEN)

    def test_explain_lists_source(self) -> None:
        # 查询词会被切成中文二元组（维特/特比），explain 以 token 为键
        rows = synonyms.explain(["维特比"])
        self.assertTrue(any("viterbi" in extra for _, extra in rows))


class IndexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.index = Index(Path(self.tmp.name) / "t.sqlite3")
        for path in sorted(SAMPLES.glob("*.md")):
            if path.name.lower().startswith("readme"):
                continue
            self.index.import_file(path)

    def tearDown(self) -> None:
        self.index.close()
        self.tmp.cleanup()

    def test_import_counts(self) -> None:
        stats = self.index.stats()
        self.assertEqual(stats["papers"], 5)
        self.assertGreater(stats["passages"], 15)

    def test_search_hits_glr_paper(self) -> None:
        hits = self.index.search("广义似然比 GLR 事件检测", top_k=5)
        self.assertTrue(hits)
        self.assertIn("anderson", " ".join(h.paper_id for h in hits))

    def test_year_filter(self) -> None:
        hits = self.index.search("事件检测 综述", top_k=5, year_from=2018)
        self.assertTrue(all((h.year or 0) >= 2018 for h in hits))

    def test_per_paper_cap(self) -> None:
        hits = self.index.search("事件 检测 功率 阶跃", top_k=6)
        counts: dict[str, int] = {}
        for hit in hits:
            counts[hit.paper_id] = counts.get(hit.paper_id, 0) + 1
        self.assertTrue(all(count <= 2 for count in counts.values()))

    def test_reimport_is_idempotent(self) -> None:
        before = self.index.stats()["passages"]
        self.index.import_file(SAMPLES / "03-anderson-2012-glr.md")
        self.assertEqual(self.index.stats()["passages"], before)

    def test_expansion_recovers_literal_miss(self) -> None:
        # 语料里只有 Viterbi，没有"维特比"；字面检索必然搜不到，扩展后应该能命中
        plain = [h.paper_id for h in self.index.search("维特比解码", top_k=5, expand=False)]
        expanded = [h.paper_id for h in self.index.search("维特比解码", top_k=5, expand=True)]
        self.assertNotIn("p-zeifman11", plain)
        self.assertIn("p-zeifman11", expanded)

    def test_expansion_can_be_disabled(self) -> None:
        self.assertEqual(set(self.index.query_weights("虚警", expand=False)), {"虚警"})
        self.assertIn("误报", self.index.query_weights("虚警", expand=True))


class MemoryParseTest(unittest.TestCase):
    def test_parse_and_dedupe(self) -> None:
        line = ('LITCORE|{"created":"2026-11-10 01:00","paper":"p-x","text":"阈值需按户标定",'
                '"topic":"事件检测","type":"finding"}')
        entries = [{"text": line}, {"content": line}, {"text": "无关内容"}]
        records = memory.parse_records(entries)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].type, "finding")

    def test_prepared_context_items(self) -> None:
        from litcontext.builder import items_from_prepared

        line = 'LITCORE|{"type":"edge","method":"GLR","dataset":"BLUED","value":"0.89"}'
        payload = ('BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n'
                   '{"items":[{"content":' + json.dumps(line) + '},{"content":"无关"}]}\n'
                   'END_POWERCONTEXT_PREPARED_CONTEXT_V1')
        items = items_from_prepared(payload)
        self.assertEqual(len(items), 2)
        records = memory.parse_records(items)
        self.assertEqual(records[0].payload["method"], "GLR")

    def test_brief_renders_citations(self) -> None:
        records = [
            memory.MemoryRecord("finding", {"paper": "p-a", "topic": "事件检测",
                                            "text": "GLR 优于固定阈值", "evidence": "BLUED"}),
            memory.MemoryRecord("decision", {"method": "HMM", "verdict": "reject",
                                             "text": "状态空间爆炸"}),
        ]
        brief = {
            "topic": "事件检测",
            "findings": [r.as_dict() for r in records if r.type == "finding"],
            "rejected": [r.as_dict() for r in records if r.type == "decision"],
            "constraints": [],
            "hits": [],
            "papers": {"p-a": {"title": "T", "authors": "A", "year": 2012, "venue": "V"}},
            "memory_calls": [],
        }
        markdown = report.render_brief_markdown(brief)
        self.assertIn("[p-a]", markdown)
        self.assertIn("HMM", markdown)


if __name__ == "__main__":
    unittest.main(verbosity=2)
