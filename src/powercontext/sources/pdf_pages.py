# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Full financial-report PDF parsing with page-level Sources and evidence-page retrieval."""

from __future__ import annotations

import hashlib
import io
import math
import re
from collections import Counter
from typing import ClassVar
from urllib.parse import quote, unquote

import pypdf
from pydantic import BaseModel, Field

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PDF_PAGE_SOURCE_NAME = "pdf-page"
_SHA256_HEX_LENGTH = 64
_QUERY_TOKEN_PATTERN = re.compile(r"[a-z]+|\d+")
# Conservative English stopwords; domain wording such as "fiscal" stays a signal.
_STOPWORDS = frozenset({
    "a", "an", "and", "any", "are", "as", "at", "be", "been", "by", "can",
    "did", "do", "does", "each", "for", "from", "had", "has", "have", "how",
    "if", "in", "into", "is", "it", "its", "more", "most", "of", "on", "or",
    "other", "our", "per", "s", "should", "so", "such", "than", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "to", "us", "was",
    "we", "were", "what", "when", "where", "which", "who", "will", "with",
    "would",
})

# Generic finance vocabulary: a question concept maps to the wording filings
# actually use. This is domain knowledge, never document- or question-specific.
# Each rule is (trigger tokens, expansion phrases, statement-title phrases).
_INTENT_RULES: tuple[tuple[frozenset[str], tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]], ...] = (
    ({"quick", "liquidity", "solvent"},
     (("current", "assets"), ("current", "liabilities"), ("liquidity",), ("capital", "resources"), ("working", "capital")),
     (("consolidated", "balance", "sheet"),)),
    ({"margin"},
     (("gross", "profit"), ("operating", "income"), ("statements", "income"), ("statements", "operations"), ("total", "revenues")),
     (("consolidated", "statement", "income"), ("consolidated", "statement", "operation"))),
    ({"legal", "battles", "litigation", "lawsuits", "suits", "disputes"},
     (("legal", "proceedings"), ("legal", "proceeding"), ("litigation",), ("contingencies",), ("contingency",), ("legal", "matters")),
     (("item", "3", "legal"),)),
    ({"geographies", "geography", "regions"},
     (("geographic",), ("geographic", "regions"), ("geographic", "operations"), ("united", "states")),
     (("item", "1", "business"),)),
    ({"products", "product", "services", "service", "industry", "industries", "offerings"},
     (("major", "products",), ("products", "services",)),
     (("item", "1", "business"),)),
    ({"customers", "customer", "client", "members", "member"},
     (("major", "customers"), ("customers",), ("customer", "concentration"), ("key", "customers")),
     (("item", "7", "management"),)),
    ({"concentration"},
     (("concentration",), ("concentrated",), ("customers",), ("one", "customer"), ("single", "customer")),
     (("one", "customer"), ("single", "customer"))),
    ({"liability", "liabilities", "assets"},
     (("total", "liabilities"), ("balance", "sheets"), ("total", "assets")),
     (("consolidated", "balance", "sheet"),)),
    ({"tax"},
     (("effective", "tax", "rate"), ("income", "taxes"), ("tax", "rate"), ("tax", "benefit"), ("income", "tax", "expense")),
     ()),
    ({"acquisition", "acquisitions", "acquired", "merger"},
     (("acquisition",), ("acquisitions",), ("business", "combination"), ("acquired",)),
     ()),
    ({"segment", "segments", "categories"},
     (("segment",), ("segments",), ("reportable", "segments"), ("segment", "data"), ("disaggregation",)),
     (("business", "segment", "data"),)),
    ({"cash"},
     (("cash", "flows"), ("operating", "activities"), ("investing", "activities"), ("financing", "activities")),
     (("consolidated", "statement", "cash"),)),
    ({"revenue", "revenues", "sales"},
     (("revenues",), ("net", "revenue"), ("total", "net"),
      ("results", "operations"), ("management", "discussion"), ("discussion", "analysis")),
     (("item", "7", "management"),)),
    ({"debt", "borrowings", "leverage"},
     (("debt",), ("borrowings",), ("notes", "payable"), ("long", "term", "debt")),
     ()),
    ({"employees", "employee", "workforce"},
     (("employees",), ("human", "capital")),
     ()),
)
_EXPANSION_WEIGHT = 1.6
_STATEMENT_TITLE_WEIGHT = 40.0
# Statement headings anchor the top of their own page; references elsewhere in
# notes, MD&A, audit reports and exhibit indexes must not inherit the bonus.
_HEAD_ANCHORED_PREFIX = "consolidated"
_HEAD_WINDOW = 15
_NEIGHBOR_SEEDS = 4


class PDFDocumentInput(BaseModel):
    """One complete original PDF document and its caller-assigned identity."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One extracted physical page bound to its document identity."""

    document_id: str
    document_sha256: str
    page_number: int = Field(ge=1)
    text: str


class PDFPageSource(Source):
    """One captured PDF page whose identity is document id, digest, and page number."""

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Build the stable page identity from percent-encoded identity components."""

    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must not be empty or whitespace-only")  # noqa: TRY003
    if not isinstance(document_sha256, str) or len(document_sha256) != _SHA256_HEX_LENGTH:
        raise ValueError("document_sha256 must be a 64-character lowercase hex digest")  # noqa: TRY003
    if not isinstance(page_number, int) or page_number < 1:
        raise ValueError("page_number must be a positive integer")  # noqa: TRY003
    source_id = f"pdf:{quote(document_id, safe='')}:{document_sha256}:{page_number}"
    if len(source_id) <= MAX_SOURCE_ID_LENGTH:
        return source_id
    # Extremely long document ids collapse to their digest; identity stays stable.
    collapsed = hashlib.sha256(document_id.encode("utf-8")).hexdigest()
    source_id = f"pdf:{collapsed}:{document_sha256}:{page_number}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return source_id


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page atomically: all pages or ``ValueError``."""

    document_id = value.document_id
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must not be empty or whitespace-only")  # noqa: TRY003
    content = value.content
    if not isinstance(content, (bytes, bytearray)) or not content:
        raise ValueError("PDF content must be non-empty bytes")  # noqa: TRY003
    document_sha256 = hashlib.sha256(bytes(content)).hexdigest()

    try:
        reader = pypdf.PdfReader(io.BytesIO(bytes(content)))
        if reader.is_encrypted:
            if reader.decrypt("") == pypdf.PasswordType.NOT_DECRYPTED:
                raise ValueError("PDF requires a non-empty password")  # noqa: TRY003
        texts: list[str] = []
        for page in reader.pages:
            extracted = page.extract_text()
            texts.append("" if extracted is None else extracted)
    except ValueError:
        raise
    except Exception as error:  # noqa: BLE001 - any pypdf failure is an atomic parse failure
        raise ValueError(f"cannot parse PDF document: {error}") from error

    return tuple(
        PDFPageInput(
            document_id=document_id,
            document_sha256=document_sha256,
            page_number=page_number,
            text=text,
        )
        for page_number, text in enumerate(texts, start=1)
    )


class _PDFPageSourceAdapter:
    """Resolve one page input into a captured page Source and read it back."""

    input_class: ClassVar[type[PDFPageInput]] = PDFPageInput
    name: ClassVar[str] = PDF_PAGE_SOURCE_NAME
    source_class: ClassVar[type[PDFPageSource]] = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        source_id = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=source_id,
            source_id=source_id,
            definition_version="1",
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class _PDFPageTextEvidenceProjection:
    """Project one page Source as its document identity plus extractable page text."""

    name: ClassVar[str] = TEXT_EVIDENCE_PROJECTION_KEY.name
    version: ClassVar[str] = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: ClassVar[type[PDFPageSource]] = PDFPageSource
    output_class: ClassVar[type[BaseModel]] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION: SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = (
    AdapterSourceDefinition(
        _PDFPageSourceAdapter(),
        projections=(_PDFPageTextEvidenceProjection(),),
    )
)


def _parse_page_location(source_id: str) -> tuple[str, int] | None:
    """Recover ``(document_id, page_number)`` from a ``pdf`` page source id."""

    parts = source_id.split(":")
    if len(parts) != 4 or parts[0] != "pdf":
        return None
    try:
        return unquote(parts[1]), int(parts[3])
    except ValueError:
        return None


def _raw_tokens(question: str) -> tuple[str, ...]:
    return tuple(_QUERY_TOKEN_PATTERN.findall(question.lower()))


def _stem(token: str) -> str:
    """Light plural normalization so ``customer`` matches ``customers``.

    Applied identically to questions, pages and intent phrases, so the word
    spaces of all three stay comparable; conservative suffix rules only.
    """

    if len(token) >= 4 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _stem_phrase(phrase: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_stem(token) for token in phrase)


def _filtered_stream(text: str) -> tuple[str, ...]:
    """Content token stream: stopwords and single letters dropped, then stemmed.

    Possessives (``Boeing ' s``) and filler words vanish here, so adjacent
    n-grams match filing phrases like ``statements of income``. One-letter
    digits survive (``Item 1``), one-letter words do not."""

    return tuple(
        _stem(token)
        for token in _QUERY_TOKEN_PATTERN.findall(text.lower())
        if token not in _STOPWORDS and (len(token) >= 2 or token.isdigit())
    )


def _query_tokens(question: str) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Content tokens of the question in the same word space as the gold metric."""

    stream = _filtered_stream(question)
    tokens = tuple(dict.fromkeys(stream))
    bigrams = tuple(zip(stream, stream[1:]))
    return tokens, bigrams


def _page_tokens(page_text: str) -> Counter[str]:
    return Counter(_QUERY_TOKEN_PATTERN.findall(page_text.lower()))


def _page_ngrams(stream: tuple[str, ...]) -> frozenset[tuple[str, ...]]:
    """Adjacent 1-, 2- and 3-grams of one page's filtered token stream."""

    grams: set[tuple[str, ...]] = set(stream)
    grams.update(zip(stream, stream[1:]))
    grams.update(zip(stream, stream[1:], stream[2:]))
    return frozenset(grams)


def _intent_expansions(raw: tuple[str, ...]) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    """Collect expansion and statement-title phrases for every matched concept."""

    expansions: list[tuple[str, ...]] = []
    titles: list[tuple[str, ...]] = []
    for triggers, expansion_phrases, title_phrases in _INTENT_RULES:
        if any(token in triggers for token in raw):
            expansions.extend(expansion_phrases)
            titles.extend(title_phrases)
    return tuple(dict.fromkeys(expansions)), tuple(dict.fromkeys(titles))


class _PageIndex:
    """Cached lexical index over every active page entry of one Memory head.

    Entries are enumerated through the public ``memory.list()`` API so scoring sees the
    whole document split with exact corpus statistics instead of the FTS channel's
    admission-filtered pool. Entries are immutable per revision, so the index is reused
    across questions until the Memory head changes.
    """

    def __init__(self, memory_ref_key: tuple, records: list) -> None:
        self.memory_ref_key = memory_ref_key
        self.records = records
        self.counts: list[Counter[str]] = []
        self.ngrams: list[frozenset[tuple[str, ...]]] = []
        self.head_ngrams: list[frozenset[tuple[str, ...]]] = []
        self.lengths: list[int] = []
        self.document_frequency = Counter()
        for record in records:
            entry = record.entry
            body = self._page_body(entry.text)
            raw_tokens = _QUERY_TOKEN_PATTERN.findall(body.lower())
            counts = Counter(_stem(token) for token in raw_tokens)
            self.counts.append(counts)
            stream = _filtered_stream(body)
            self.ngrams.append(_page_ngrams(stream))
            self.head_ngrams.append(_page_ngrams(stream[:_HEAD_WINDOW]))
            self.lengths.append(sum(counts.values()))
            self.document_frequency.update(set(counts))
        self.page_count = max(len(records), 1)
        self.avg_length = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0

    @staticmethod
    def _page_body(entry_text: str) -> str:
        # Entry text is "DOCUMENT_ID\nPAGE_TEXT" stripped; drop the identity line.
        return entry_text.split("\n", 1)[1] if "\n" in entry_text else ""

    def idf(self, token: str) -> float:
        df = self.document_frequency.get(token, 0)
        return math.log(1.0 + (self.page_count - df + 0.5) / (df + 0.5))

    def score(
        self,
        tokens: tuple[str, ...],
        bigrams: tuple[tuple[str, str], ...],
        expansions: tuple[tuple[str, ...], ...],
        titles: tuple[tuple[str, ...], ...],
        position: int,
    ) -> float:
        counts = self.counts[position]
        ngrams = self.ngrams[position]
        length = max(self.lengths[position], 1)
        total = 0.0
        informative_tokens: list[str] = []
        informative_matched = 0
        for token in tokens:
            tf = counts.get(token, 0)
            if tf > 0 and self.idf(token) > 1.0 and not token.isdigit():
                informative_tokens.append(token)
            if tf == 0:
                continue
            idf = self.idf(token)
            if idf > 1.0 and not token.isdigit():
                informative_matched += 1
            # BM25: tf saturation + length normalization.
            norm_tf = (tf * 2.2) / (tf + 1.2 * (0.4 + 0.6 * length / self.avg_length))
            weight = 2.0 if token.isdigit() else 1.0
            total += weight * idf * norm_tf
        if informative_tokens:
            total += 3.0 * informative_matched / len(informative_tokens)
        for first, second in bigrams:
            if (first, second) in ngrams:
                # Exact phrase on the page is a strong signal.
                total += 2.5 * (self.idf(first) + self.idf(second))
            elif counts.get(first, 0) > 0 and counts.get(second, 0) > 0:
                # Mere co-occurrence is a weak hint only.
                total += 0.8 * (self.idf(first) + self.idf(second))
        # Concept expansions speak the filing's own section vocabulary.
        for phrase in expansions:
            stemmed = _stem_phrase(phrase)
            if len(stemmed) == 1:
                tf = counts.get(stemmed[0], 0)
                if tf > 0:
                    idf = self.idf(stemmed[0])
                    norm_tf = (tf * 2.2) / (tf + 1.2 * (0.4 + 0.6 * length / self.avg_length))
                    total += _EXPANSION_WEIGHT * idf * norm_tf
            elif stemmed in ngrams:
                total += _EXPANSION_WEIGHT * sum(self.idf(token) for token in stemmed)
        for title in titles:
            stemmed = _stem_phrase(title)
            # Statement titles are page headings; 10-K item headings may sit
            # mid-page because several items share one physical page. One title
            # bonus per page is enough for any heading match.
            anchored = stemmed[0] == _HEAD_ANCHORED_PREFIX
            grams = self.head_ngrams[position] if anchored else ngrams
            if stemmed in grams:
                total += _STATEMENT_TITLE_WEIGHT
                break
        return total


_INDEX_CACHE: dict = {}


def _detect_document(question: str, doc_names: tuple[str, ...]) -> str | None:
    """Identify the document a question targets from its company-name mention.

    A question about a filing almost always names the company. Company names are
    matched against document ids: exact token match (``amd``, ``amcor``, ``pepsico``)
    or, for multi-word names, the concatenated letter form (``americanexpress``)
    appearing in the letter stream of the question. Abbreviated mentions such as
    ``amex`` fall back to an in-order subsequence match against the letter stream
    of exactly one document name.
    """

    raw = _QUERY_TOKEN_PATTERN.findall(question.lower())
    if not raw:
        return None
    letters = re.sub(r"[^a-z]", "", "".join(raw))
    for doc_id in doc_names:
        # Letter groups of the document id: "AMERICANEXPRESS_2022_10K" ->
        # ["americanexpress"]; digits and the "10K" suffix are dropped.
        names = [token for token in re.findall(r"[a-z]+", doc_id.lower()) if len(token) >= 3]
        for name in names:
            if name in raw or (len(name) >= 10 and name in letters):
                return doc_id
    # Abbreviation fallback: "amex" is an in-order subsequence of "americanexpress".
    candidates = []
    for doc_id in doc_names:
        name = "".join(re.findall(r"[a-z]+", doc_id.lower()))
        for token in raw:
            if len(token) < 4 or not token.isalpha() or token in _STOPWORDS:
                continue
            if _is_subsequence(token, name):
                candidates.append(doc_id)
                break
    unique = set(candidates)
    return candidates[0] if len(unique) == 1 else None


def _is_subsequence(needle: str, haystack: str) -> bool:
    position = 0
    for char in needle:
        position = haystack.find(char, position)
        if position < 0:
            return False
        position += 1
    return True


def _page_index(memory, records: list) -> tuple[_PageIndex, dict[str, list[int]], dict[str, _PageIndex]]:
    """Build (or fetch cached) the full-corpus index plus per-document sub-indexes.

    Per-document indexes give document-local BM25 statistics, which sharply reduce
    boilerplate noise once the target document is detected from the question.
    """

    head = records[0].memory_ref if records else None
    key = (head.family, head.artifact_id, head.revision, len(records)) if head is not None else None
    cached = _INDEX_CACHE.get("index")
    if cached is not None and key is not None and cached[0].memory_ref_key == key:
        return cached
    index = _PageIndex(key, records)
    doc_positions: dict[str, list[int]] = {}
    for position, record in enumerate(records):
        doc = record.entry.text.split("\n", 1)[0] if "\n" in record.entry.text else ""
        doc_positions.setdefault(doc, []).append(position)
    doc_indexes = {
        doc: _PageIndex(None, [records[position] for position in positions])
        for doc, positions in doc_positions.items()
    }
    cached = (index, doc_positions, doc_indexes)
    _INDEX_CACHE["index"] = cached
    return cached


def _record_location(record) -> tuple[str, int] | None:
    for reference in record.entry.sources:
        location = _parse_page_location(reference.source_id)
        if location is not None:
            return location
    return None


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple:
    """Search one scoped Memory and return at most ``limit`` distinct page citations.

    Retrieval scores every active page entry of the scoped Memory with corpus-exact
    idf-weighted lexical overlap plus question-bigram phrase bonuses, translates the
    question's concepts into the filing's own section vocabulary, and fills spare
    slots with pages adjacent to the strongest hits so multi-page evidence near a
    located section is not lost. All returned citations point at real Memory entries.
    """

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")  # noqa: TRY003
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003

    from powercontext.builtin.runtime import SearchMemoryRequest  # noqa: PLC0415

    page = await memory.list()
    if page.memory_ref is None or not page.entries:
        return ()
    records = [record for record in page.entries if record.state == "active"]
    if not records:
        return ()
    index, doc_positions, doc_indexes = _page_index(memory, records)

    raw = _raw_tokens(question)
    tokens, bigrams = _query_tokens(question)
    expansions, titles = _intent_expansions(raw)

    doc_id = _detect_document(question, tuple(doc_positions))
    if doc_id is not None:
        positions = doc_positions[doc_id]
        scoring_index = doc_indexes[doc_id]
        candidates = [(subset_position, records[original]) for subset_position, original in enumerate(positions)]
    else:
        scoring_index = index
        candidates = list(enumerate(records))

    fts_bonus: dict[tuple[str, str], float] = {}
    try:
        result = await memory.search(SearchMemoryRequest(query=question, mode="fts", limit=max(limit * 3, 30)))
        total = max(len(result.hits), 1)
        for position, hit in enumerate(result.hits if result.hits else ()):
            fts_bonus[(hit.entry_id, hit.entry_version_id)] = 0.25 * (1.0 - position / total)
    except Exception:  # noqa: BLE001 - FTS is only a tie-break signal, never fatal
        fts_bonus = {}

    ranked = []
    locations: dict[object, tuple[str, int] | None] = {}
    for subset_position, record in candidates:
        entry = record.entry
        score = scoring_index.score(tokens, bigrams, expansions, titles, subset_position)
        score += fts_bonus.get((entry.entry_id, entry.entry_version_id), 0.0)
        ranked.append((-score, entry.entry_id, record))
        locations[id(record)] = _record_location(record)
    ranked.sort(key=lambda item: (item[0], item[1]))

    # Primary slots follow the combined score; the rest favor pages adjacent to the
    # strongest hits, because FinanceBench evidence frequently spans neighbouring
    # pages of the section one strong hit already located.
    primary_count = max(4, int(limit * 0.6)) if limit >= 6 else limit
    selected: list = []
    seen_pages: set[tuple[str, int]] = set()

    def _try_add(record) -> bool:
        location = locations.get(id(record))
        if location is not None:
            if location in seen_pages:
                return False
            seen_pages.add(location)
        selected.append(record)
        return True

    seeds: list = []
    for _, _, record in ranked:
        if len(selected) >= primary_count:
            break
        if _try_add(record) and len(seeds) < _NEIGHBOR_SEEDS:
            seeds.append(record)

    by_page: dict[tuple[str, int], object] = {}
    for record in records:
        location = locations.get(id(record))
        if location is not None and location not in by_page:
            by_page[location] = record
    if seeds and len(selected) < limit:
        for distance in (1, 2, 3, 4):
            for seed in seeds:
                if len(selected) >= limit:
                    break
                location = locations.get(id(seed))
                if location is None:
                    continue
                document, page_number = location
                for neighbor_number in (page_number - distance, page_number + distance):
                    if len(selected) >= limit:
                        break
                    neighbor = by_page.get((document, neighbor_number))
                    if neighbor is not None:
                        _try_add(neighbor)

    for _, _, record in ranked:
        if len(selected) >= limit:
            break
        _try_add(record)
    return tuple(record.citation for record in selected)


__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFPageInput",
    "PDFPageSource",
    "PDFDocumentInput",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
