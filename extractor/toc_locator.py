import re
from dataclasses import dataclass

from extractor.pdf_reader import PdfReader
from extractor.toc_page_parser import TocEntryPage


@dataclass
class TocEntryMatched:
    title: str
    level: int
    page: int | None = None
    page_hint: int | None = None
    score: int | None = None
    unmatched: bool = False


class TocLocator:
    def __init__(self, reader: PdfReader, threshold: int = 85):
        self.reader = reader
        self.threshold = threshold

    def locate(self, entries: list[TocEntryPage], exclude_pages: list[int] | None = None) -> list[TocEntryMatched]:
        self._exclude = set(exclude_pages or [])
        results = []
        for entry in entries:
            matched = self._locate_one(entry)
            results.append(matched)
        return results

    def _locate_one(self, entry: TocEntryPage) -> TocEntryMatched:
        # 优先使用page_hint（目录页标注的页码更可靠）
        if entry.page_hint is not None and 0 < entry.page_hint <= self.reader.page_count:
            hint_page = entry.page_hint - 1  # 转0-based
            # 尝试在hint附近搜索确认
            keywords = self._prepare_keywords(entry.title)
            start = max(0, hint_page - 5)
            end = min(self.reader.page_count, hint_page + 5)
            pages = [p for p in range(start, end) if p not in self._exclude]

            best_result = None
            for kw in keywords:
                search_results = self.reader.search_text(
                    kw, pages=pages, threshold=max(self.threshold, 95)
                )
                for r in search_results:
                    if best_result is None or r.score > best_result.score:
                        best_result = r

            if best_result and best_result.score >= 95:
                return TocEntryMatched(
                    title=entry.title,
                    level=entry.level,
                    page=best_result.page,
                    page_hint=entry.page_hint,
                    score=best_result.score,
                )
            # 搜索不到或不可靠，直接信任page_hint
            return TocEntryMatched(
                title=entry.title,
                level=entry.level,
                page=hint_page,
                page_hint=entry.page_hint,
                score=None,
            )
        else:
            # 没有page_hint，全文搜索
            keywords = self._prepare_keywords(entry.title)
            all_pages = [p for p in range(self.reader.page_count) if p not in self._exclude]
            best_result = None
            for kw in keywords:
                search_results = self.reader.search_text(
                    kw, pages=all_pages, threshold=self.threshold
                )
                for r in search_results:
                    if best_result is None or r.score > best_result.score:
                        best_result = r

            if best_result:
                return TocEntryMatched(
                    title=entry.title,
                    level=entry.level,
                    page=best_result.page,
                    page_hint=entry.page_hint,
                    score=best_result.score,
                )
            return TocEntryMatched(
                title=entry.title,
                level=entry.level,
                page_hint=entry.page_hint,
                unmatched=True,
            )

    def _prepare_keywords(self, title: str) -> list[str]:
        """生成多个搜索关键词变体（完整标题 + 去前缀版）。"""
        keywords = [title.replace(" ", "")]
        # 尝试去掉编号前缀，只搜索正文部分
        stripped = re.sub(
            r"^(第[一二三四五六七八九十\d]+[章节篇]|"
            r"\d+\.\d+(\.\d+)?|"
            r"[（(][一二三四五六七八九十]+[）)]|"
            r"[一二三四五六七八九十]+[、．.])"
            r"\s*",
            "", title
        ).strip()
        if stripped and stripped != title and len(stripped) >= 2:
            keywords.append(stripped.replace(" ", ""))
        return keywords
