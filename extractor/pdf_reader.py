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
        pages = self._resolve_pages(pages)
        results = []
        for page_num in pages:
            page_text = self._doc[page_num].get_text()
            # 1. 精确文本匹配（最快：C级别）
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
                else:
                    results.append(SearchResult(
                        text=keyword,
                        page=page_num,
                        bbox=(0, 0, 0, 0),
                        score=100,
                    ))
                # 找到了，跳过本页
                continue
            # 2. 去空格精确匹配
            normalized_key = keyword.replace(" ", "")
            normalized_text = page_text.replace(" ", "")
            if normalized_key in normalized_text:
                results.append(SearchResult(
                    text=keyword,
                    page=page_num,
                    bbox=(0, 0, 0, 0),
                    score=95,
                ))
                continue
            # 3. 预过滤：关键词首字出现才做模糊匹配
            first_chars = normalized_key[:3]
            if not any(c in normalized_text for c in first_chars):
                continue
            # 4. 模糊匹配
            from thefuzz import fuzz
            # 只匹配前2000字符（正文开头通常有标题）
            score = fuzz.partial_ratio(normalized_key, normalized_text[:2000])
            if score >= threshold:
                results.append(SearchResult(
                    text=keyword,
                    page=page_num,
                    bbox=(0, 0, 0, 0),
                    score=score,
                ))
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
