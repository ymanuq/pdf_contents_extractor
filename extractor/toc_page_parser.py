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

    # 标题前缀模式 -> 建议层级
    PREFIX_PATTERNS = [
        (re.compile(r"第[一二三四五六七八九十百千\d]+[章节]"), 1),
        (re.compile(r"第[一二三四五六七八九十百千\d]+篇"), 1),
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
        self._ad_lines = None  # 缓存的广告行集合

    def _build_ad_filter(self, doc: pymupdf.Document):
        """预计算跨页重复的广告行。"""
        from collections import Counter
        line_counts = Counter()
        sample_pages = min(10, doc.page_count)
        for i in range(sample_pages):
            # 跳过前几页（封面、目录）
            if i < 3:
                continue
            text = doc[i].get_text()
            for line in text.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                normalized = re.sub(r"\s+", "", stripped)
                if len(normalized) > 10:
                    line_counts[normalized] += 1
        # 出现在3个以上页面 = 广告/水印
        self._ad_lines = {k for k, v in line_counts.items() if v >= 3}

    def _is_ad_line(self, line: str) -> bool:
        """检查是否是广告行（子串匹配）。"""
        normalized = re.sub(r"\s+", "", line)
        if len(normalized) < 10:
            return False
        if not self._ad_lines:
            return False
        for ad in self._ad_lines:
            if normalized in ad or ad in normalized:
                return True
        return False

    def find_toc_page(self, doc: pymupdf.Document, search_pages=None) -> int | None:
        """返回目录所在的页码(0-based)，找不到返回None。"""
        # 预建广告过滤器
        self._build_ad_filter(doc)

        user_specified = search_pages is not None

        if search_pages is not None:
            candidates = search_pages
        else:
            candidates = list(range(min(self.max_search_pages, doc.page_count)))

        # 找带"目录"关键词的页面
        for page_num in candidates:
            if page_num >= doc.page_count:
                break
            text = doc[page_num].get_text()
            if self._contains_toc_keyword(text) and self._is_toc_page(text):
                return page_num

        # 如果用户指定了页面，直接返回（不再做fallback搜索）
        if user_specified:
            if len(candidates) == 1:
                return candidates[0]
            return None

        # 全文找带关键词的
        for page_num in range(doc.page_count):
            text = doc[page_num].get_text()
            if self._contains_toc_keyword(text) and self._is_toc_page(text):
                return page_num

        # fallback：前20%页面中找TOC特征最强的
        best_page = None
        best_score = 0
        total = doc.page_count
        max_scan = max(30, int(total * 0.2))
        for page_num in range(max_scan):
            text = doc[page_num].get_text()
            score = self._toc_page_score(text, page_num, total)
            if score > best_score:
                best_score = score
                best_page = page_num
        if best_score >= 4:
            return best_page
        return None

    def parse_entries(self, doc: pymupdf.Document, toc_page_num: int) -> list[TocEntryPage]:
        """从目录页解析条目列表。"""
        raw_lines = self._extract_raw_lines(doc, toc_page_num)
        merged = self._merge_split_lines(raw_lines)
        entries = []
        for line_num, line_text in enumerate(merged):
            entry = self._parse_line(line_text, line_num)
            if entry:
                entries.append(entry)
        return self._refine_levels(entries)

    def _extract_raw_lines(self, doc: pymupdf.Document, page_num: int) -> list[str]:
        """提取原始行（过滤广告、纯数字、OCR噪音）。"""
        page = doc[page_num]
        text = page.get_text("text")
        lines = []
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            # 保留纯页码行（合并时会用到）
            if self._is_ad_line(stripped):
                continue
            if self._is_noise_line(stripped):
                continue
            lines.append(stripped)
        return lines

    def _is_noise_line(self, line: str) -> bool:
        """判断是否是OCR噪音行（无有效中文内容）。"""
        # 先检查是否是广告相关内容
        if self._contains_ad_keyword(line):
            return True
        if re.search(r"[一-鿿]", line):
            return False
        if re.match(r"^[a-zA-Z\s\.\,\;\-]+$", line):
            return True
        if len(line) < 4 and not self._has_page_number(line):
            return True
        return False

    def _contains_ad_keyword(self, text: str) -> bool:
        """检查文本是否包含广告关键词。"""
        keywords = [
            "交易手续费", "期货开户", "客服微信", "赔偿差价",
            "7help", "书籍下载",
        ]
        for kw in keywords:
            if kw in text:
                return True
        return False

    def _merge_split_lines(self, lines: list[str]) -> list[str]:
        """合并OCR拆分的行：将标题+乱码+页码重组为单个逻辑行。"""
        # 第1步：合并被拆分的编号（如"第 10"+"章"）
        lines = self._merge_split_prefix(lines)
        # 第2步：以标题前缀为边界，分组合并
        merged = []
        buf = []
        for line in lines:
            norm = self._normalize_for_match(line)
            is_new = self._match_prefix(norm)
            if not is_new and not buf:
                # 无前缀时，需要足够的中文内容才认为是目录条目
                cjk_chars = re.findall(r"[一-鿿]", line)
                is_new = len(cjk_chars) >= 3 and not self._is_pure_page_number(line)

            if is_new:
                if buf:
                    merged.append(" ".join(buf))
                buf = [line]
            elif buf:
                buf.append(line)
        if buf:
            merged.append(" ".join(buf))
        return merged

    def _merge_split_prefix(self, lines: list[str]) -> list[str]:
        """合并被OCR拆分的标题编号（如'第 10' + '章'）。"""
        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            norm = self._normalize_for_match(line)
            # 检查是否以"第\d+$"结尾（编号被拆分）
            m = re.match(r"第[一二三四五六七八九十\d]+$", norm)
            if m and i + 1 < len(lines):
                next_norm = self._normalize_for_match(lines[i + 1])
                if re.match(r"[章节篇]", next_norm):
                    result.append(line + " " + lines[i + 1])
                    i += 2
                    continue
            result.append(line)
            i += 1
        return result

    def _parse_line(self, line: str, line_number: int) -> TocEntryPage | None:
        """解析单行目录条目。"""
        if self._is_toc_title_line(line):
            return None
        page_hint = self._extract_page_hint(line)
        title = self._clean_title(line)
        if not title or len(title) < 3:
            return None
        has_cjk = bool(re.search(r"[一-鿿]", title))
        has_prefix = self._match_prefix(self._normalize_for_match(line))
        if not has_cjk and not has_prefix:
            return None
        level = self._detect_level(line, title)
        return TocEntryPage(
            title=title,
            level=level,
            page_hint=page_hint,
            line_number=line_number,
        )

    def _clean_title(self, line: str) -> str:
        """清理标题文本：去OCR噪音、页码、引导点，连接分写中文。"""
        line = re.sub(r"\.{2,}.*$", "", line)
        line = re.sub(r"\s*\d{1,4}\s*$", "", line)
        line = re.sub(r"\.{3,}", " ", line)
        line = self._remove_ocr_noise(line)
        line = self._join_spaced_cjk(line)
        return line.strip()

    def _remove_ocr_noise(self, text: str) -> str:
        text = re.sub(r"\b([a-zA-Z]{1,4}\s+){2,}[a-zA-Z]{1,15}\b", " ", text)
        text = re.sub(r"\b[a-zA-Z]{8,}\b", " ", text)
        text = re.sub(r'\s+[,.，。、；;:""'']+\s*', ' ', text)
        return text

    def _join_spaced_cjk(self, text: str) -> str:
        text = re.sub(r"([一-鿿㐀-䶿])\s+([一-鿿㐀-䶿])", r"\1\2", text)
        return text

    def _detect_level(self, line: str, title: str) -> int:
        normalized = self._normalize_for_match(line)
        for pattern, level in self.PREFIX_PATTERNS:
            if pattern.match(normalized) or pattern.match(self._normalize_for_match(title)):
                return level
        return 1

    def _match_prefix(self, normalized_line: str) -> bool:
        return any(p[0].match(normalized_line) for p in self.PREFIX_PATTERNS)

    def _normalize_for_match(self, text: str) -> str:
        return re.sub(r"\s+", "", text)

    def _extract_page_hint(self, line: str) -> int | None:
        """提取合适的页码数字（TOC条目行尾）。"""
        # 优先取行尾数字
        m = re.search(r"(\d{1,4})\s*$", line)
        if m:
            num = int(m.group(1))
            if 1 <= num <= 9999:
                return num
        # fallback：找行中最后一个独立数字
        nums = re.findall(r"(?<!\d)(\d{1,4})(?!\d)", line)
        for n in reversed(nums):
            num = int(n)
            if 1 <= num <= 9999:
                return num
        return None

    def _contains_toc_keyword(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text)
        for kw in self.TOC_KEYWORDS:
            if kw in normalized or kw in text:
                return True
        return False

    def _is_toc_page(self, text: str) -> bool:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) < 5:
            return False
        entry_count = 0
        for line in lines:
            if self._has_page_number(line):
                entry_count += 1
            if self._match_prefix(self._normalize_for_match(line)):
                entry_count += 1
        return entry_count >= 3

    def _toc_page_score(self, text: str, page_num: int = 0, total_pages: int = 1) -> int:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        score = 0
        for line in lines:
            has_num = self._has_page_number(line)
            has_prefix = self._match_prefix(self._normalize_for_match(line))
            if has_num and has_prefix:
                score += 2
            elif has_num:
                score += 1
        if page_num < total_pages * 0.1:
            score = int(score * 1.5)
        elif page_num < total_pages * 0.2:
            score = int(score * 1.2)
        elif page_num > total_pages * 0.8:
            score = int(score * 0.3)
        return score

    def _is_toc_title_line(self, line: str) -> bool:
        stripped = re.sub(r"\s+", "", line.strip())
        return stripped in ("目录", "目次", "Contents", "CONTENTS")

    def _has_page_number(self, line: str) -> bool:
        return bool(re.search(r"\d{1,4}\s*$", line))

    def _is_pure_page_number(self, line: str) -> bool:
        return bool(re.match(r"^\s*\d{1,4}\s*$", line))

    def _refine_levels(self, entries: list[TocEntryPage]) -> list[TocEntryPage]:
        if not entries:
            return entries
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
            min_level = min(e.level for e in entries)
            if min_level > 1:
                for e in entries:
                    e.level -= (min_level - 1)
        return entries
