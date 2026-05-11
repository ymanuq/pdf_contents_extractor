from dataclasses import dataclass, field

from extractor.pdf_reader import PdfReader
from extractor.toc_page_parser import TocEntryPage


@dataclass
class TocEntryMatched:
    title: str
    level: int
    page: int | None = None       # None表示未匹配到
    page_hint: int | None = None
    score: int | None = None
    unmatched: bool = False


class TocLocator:
    def __init__(self, reader: PdfReader, threshold: int = 85):
        self.reader = reader
        self.threshold = threshold

    def locate(self, entries: list[TocEntryPage]) -> list[TocEntryMatched]:
        results = []
        for entry in entries:
            matched = self._locate_one(entry)
            results.append(matched)
        return results

    def _locate_one(self, entry: TocEntryPage) -> TocEntryMatched:
        keyword = self._prepare_keyword(entry.title)
        pages = None
        if entry.page_hint:
            # 在标注页码附近搜索（±3页）
            start = max(0, entry.page_hint - 4)
            end = min(self.reader.page_count, entry.page_hint + 3)
            pages = list(range(start, end))

        search_results = self.reader.search_text(
            keyword, pages=pages, threshold=self.threshold
        )

        if not search_results and pages:
            # 附近没找到，全文搜索
            search_results = self.reader.search_text(
                keyword, pages=None, threshold=self.threshold
            )

        if search_results:
            best = search_results[0]
            return TocEntryMatched(
                title=entry.title,
                level=entry.level,
                page=best.page,
                page_hint=entry.page_hint,
                score=best.score,
            )
        else:
            return TocEntryMatched(
                title=entry.title,
                level=entry.level,
                page_hint=entry.page_hint,
                unmatched=True,
            )

    def _prepare_keyword(self, title: str) -> str:
        """清理标题，去除编号前缀只保留主题文本用于搜索。"""
        import re
        # 尝试提取：编号 + 空格 + 正文 的模式
        # 如 "第1章 引言" -> "引言"
        # 如 "1.1 背景" -> "背景"
        # 但保留完整标题作为搜索词（更精确）
        return title.strip()
