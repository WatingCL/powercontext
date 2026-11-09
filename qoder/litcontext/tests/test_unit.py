"""单元测试：不依赖 PowerContext 服务，`python -m unittest` 直接跑。

    cd qoder/litcontext && python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from litcontext import memory, report  # noqa: E402
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
