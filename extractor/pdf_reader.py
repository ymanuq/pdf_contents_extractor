from dataclasses import dataclass

import pymupdf


@dataclass
class TextBlock:
    text: str
    page: int          # 0-based
    font_size: float
    font_name: str
    is_bold: bool
    bbox: tuple        # (x0, y0, x1, y1)


@dataclass
class SearchResult:
    text: str
    page: int          # 0-based
    bbox: tuple
    score: int         # 0-100


class PdfReader:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self._doc = pymupdf.open(filepath)

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    def extract_text_blocks(self, pages=None) -> list[TextBlock]:
        pages = self._resolve_pages(pages)
        blocks = []
        for page_num in pages:
            page = self._doc[page_num]
            for block in page.get_text("dict")["blocks"]:
                if block["type"] != 0:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if not text:
                            continue
                        font_name = span["font"]
                        font_size = round(span["size"], 1)
                        blocks.append(TextBlock(
                            text=text,
                            page=page_num,
                            font_size=font_size,
                            font_name=font_name,
                            is_bold="Bold" in font_name or "bold" in font_name,
                            bbox=span["bbox"],
                        ))
        return blocks

    def extract_page_text(self, page_num: int) -> str:
        return self._doc[page_num].get_text()

    def search_text(self, keyword: str, pages=None, threshold: int = 85) -> list[SearchResult]:
        from thefuzz import fuzz

        pages = self._resolve_pages(pages)
        results = []
        for page_num in pages:
            page_text = self._doc[page_num].get_text()
            # 先尝试精确搜索
            if keyword in page_text:
                search = self._doc[page_num].search_for(keyword)
                if search:
                    for rect in search:
                        results.append(SearchResult(
                            text=keyword,
                            page=page_num,
                            bbox=rect,
                            score=100,
                        ))
                    continue
            # 模糊搜索：滑动窗口匹配
            score = fuzz.partial_ratio(keyword, page_text)
            if score >= threshold:
                results.append(SearchResult(
                    text=keyword,
                    page=page_num,
                    bbox=(0, 0, 0, 0),
                    score=score,
                ))
        # 去重+保留每页最高分
        return self._dedupe(results)

    def close(self):
        self._doc.close()

    def _resolve_pages(self, pages) -> list[int]:
        if pages is None:
            return list(range(self._doc.page_count))
        if isinstance(pages, int):
            return [pages]
        return list(pages)

    def _dedupe(self, results: list[SearchResult]) -> list[SearchResult]:
        page_best = {}
        for r in results:
            if r.page not in page_best or r.score > page_best[r.page].score:
                page_best[r.page] = r
        return sorted(page_best.values(), key=lambda r: r.score, reverse=True)
