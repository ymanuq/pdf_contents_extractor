import re
from dataclasses import dataclass

import pymupdf


@dataclass
class TocEntryPage:
    title: str
    level: int           # 1-based
    page_hint: int | None
    line_number: int


class TocPageParser:
    TOC_KEYWORDS = ["目录", "目次", "Contents", "CONTENTS"]
    TOC_KEYWORD_PAGE = "目录"

    # 标题前缀模式 -> 建议层级
    PREFIX_PATTERNS = [
        (re.compile(r"第[一二三四五六七八九十百千\d]+[章节]"), 1),
        (re.compile(r"Chapter\s+\d+", re.IGNORECASE), 1),
        (re.compile(r"(?:Part|PART)\s+\d+", re.IGNORECASE), 1),
        (re.compile(r"\d+\.\d+\.\d+"), 3),
        (re.compile(r"\d+\.\d+"), 2),
        (re.compile(r"[（(][一二三四五六七八九十]+[）)]"), 2),
        (re.compile(r"[一二三四五六七八九十]+[、．.]"), 2),
        (re.compile(r"[一二三四五六七八九十]+[）)]"), 2),
    ]

    def __init__(self, max_search_pages: int = 20):
        self.max_search_pages = max_search_pages

    def find_toc_page(self, doc: pymupdf.Document, search_pages=None) -> int | None:
        """返回目录所在的页码(0-based)，找不到返回None。"""
        if search_pages is not None:
            candidates = search_pages
        else:
            candidates = list(range(min(self.max_search_pages, doc.page_count)))

        for page_num in candidates:
            if page_num >= doc.page_count:
                break
            text = doc[page_num].get_text()
            if self._contains_toc_keyword(text) and self._is_toc_page(text):
                return page_num

        # 全文扫描
        for page_num in range(doc.page_count):
            text = doc[page_num].get_text()
            if self._contains_toc_keyword(text) and self._is_toc_page(text):
                return page_num
        return None

    def _contains_toc_keyword(self, text: str) -> bool:
        """检查文本是否包含目录关键词（忽略空格）。"""
        normalized = re.sub(r"\s+", "", text)
        for kw in self.TOC_KEYWORDS:
            if kw in normalized:
                return True
        # 也检查原文（Contents 之类不需要去空格）
        for kw in self.TOC_KEYWORDS:
            if kw in text:
                return True
        return False

    def parse_entries(self, doc: pymupdf.Document, toc_page_num: int) -> list[TocEntryPage]:
        """从目录页解析条目列表。"""
        blocks = self._extract_lines(doc, toc_page_num)
        entries = []

        for line_num, line_text in enumerate(blocks):
            entry = self._parse_line(line_text, line_num)
            if entry:
                entries.append(entry)

        # 修正层级
        entries = self._refine_levels(entries)
        return entries

    def _is_toc_page(self, text: str) -> bool:
        """判断是否真的是目录页（有密集的条目特征）。"""
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        # 目录页通常有较多的行
        if len(lines) < 5:
            return False
        # 计算匹配标题模式的行数
        entry_count = 0
        for line in lines:
            if self._has_page_number(line):
                entry_count += 1
            for pattern, _ in self.PREFIX_PATTERNS:
                if pattern.match(line):
                    entry_count += 1
                    break
        return entry_count >= 3

    def _extract_lines(self, doc: pymupdf.Document, page_num: int) -> list[str]:
        """从目录页提取文本行，并合并相邻的目录页。"""
        lines = self._extract_page_lines(doc, page_num)

        # 检查下一页是否也是目录页（目录可能跨多页）
        next_page = page_num + 1
        if next_page < doc.page_count:
            next_text = doc[next_page].get_text()
            if self._is_toc_page(next_text):
                lines += self._extract_page_lines(doc, next_page)
        return lines

    def _extract_page_lines(self, doc: pymupdf.Document, page_num: int) -> list[str]:
        """提取单页的行文本。"""
        page = doc[page_num]
        text = page.get_text("text")
        lines = []
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped:
                # 跳过纯页码行和目录标题行
                if not self._is_pure_page_number(stripped):
                    lines.append(stripped)
        return lines

    def _parse_line(self, line: str, line_number: int) -> TocEntryPage | None:
        """解析单行目录条目。"""
        # 跳过目录页的标题行本身
        if self._is_toc_title_line(line):
            return None
        page_hint = self._extract_page_hint(line)
        title = self._clean_title(line)
        if not title or len(title) < 2:
            return None
        level = self._detect_level(line, title)
        return TocEntryPage(
            title=title,
            level=level,
            page_hint=page_hint,
            line_number=line_number,
        )

    def _is_toc_title_line(self, line: str) -> bool:
        """判断是否是目录页自己的标题行（如'目录'、'Contents'）。"""
        stripped = line.strip()
        if stripped in ("目录", "目次", "Contents", "CONTENTS"):
            return True
        return False

    def _extract_page_hint(self, line: str) -> int | None:
        """提取行尾的页码数字。"""
        # 匹配末尾的数字（可能前后有空格）
        m = re.search(r"(\d{1,4})\s*$", line)
        if m:
            num = int(m.group(1))
            if 1 <= num <= 9999:
                return num
        return None

    def _clean_title(self, line: str) -> str:
        """清理标题文本：去除末尾页码和中间的引导点。"""
        # 去除末尾页码
        line = re.sub(r"\.{2,}.*$", "", line)
        line = re.sub(r"\s*\d{1,4}\s*$", "", line)
        # 去除中间的引导点序列
        line = re.sub(r"\.{3,}", " ", line)
        return line.strip()

    def _detect_level(self, line: str, title: str) -> int:
        """根据前缀模式和缩进推断层级。"""
        for pattern, level in self.PREFIX_PATTERNS:
            if pattern.match(line) or pattern.match(title):
                return level
        # 默认一级
        return 1

    def _refine_levels(self, entries: list[TocEntryPage]) -> list[TocEntryPage]:
        """修正层级关系：确保层级之间的一致性。"""
        if not entries:
            return entries
        # 找到最常见的顶级编号，以此为level 1
        level1_patterns = [
            re.compile(r"第[一二三四五六七八九十百千\d]+[章节]"),
            re.compile(r"Chapter\s+\d+", re.IGNORECASE),
        ]
        has_level1 = False
        for e in entries:
            for p in level1_patterns:
                if p.match(e.title):
                    has_level1 = True
                    e.level = 1
                    break

        if not has_level1 and entries:
            # 如果所有条目的level都>=2，全部降一级
            min_level = min(e.level for e in entries)
            if min_level > 1:
                for e in entries:
                    e.level -= (min_level - 1)

        return entries

    def _has_page_number(self, line: str) -> bool:
        return bool(re.search(r"\d{1,4}\s*$", line))

    def _is_pure_page_number(self, line: str) -> bool:
        return bool(re.match(r"^\s*\d{1,4}\s*$", line))
