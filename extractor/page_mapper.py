"""印刷页码 → PDF页码 自动映射。

扫描PDF每页底部区域，检测印刷页码，建立映射表。
"""
import re
from collections import Counter

import pymupdf


class PageMapper:
    def __init__(self, doc: pymupdf.Document):
        self._doc = doc
        self._mapping: dict[int, int] | None = None  # printed_page → pdf_page(0-based)

    def build(self) -> dict[int, int]:
        raw = self._scan_all_pages()
        self._mapping = self._build_mapping(raw)
        return self._mapping

    def convert(self, printed_page: int) -> int | None:
        if self._mapping is None:
            return None
        return self._mapping.get(printed_page)

    def _scan_all_pages(self) -> list[tuple]:
        """返回 [(pdf_page(0-based), detected_printed_num), ...]."""
        results = []
        for pdf_page in range(self._doc.page_count):
            num = self._detect_page_number(pdf_page)
            if num is not None:
                results.append((pdf_page, num))
        return results

    def _detect_page_number(self, pdf_page: int) -> int | None:
        page = self._doc[pdf_page]
        h = page.rect.height
        w = page.rect.width
        clip = pymupdf.Rect(0, h * 0.95, w, h)
        text = page.get_text("text", clip=clip).strip()
        if not text:
            return None
        # "一 142 一" 格式
        m = re.search(r"[—–一\-]\s*(\d{1,4})\s*[—–一\-]", text)
        if m:
            return int(m.group(1))
        # 底部仅有数字
        m = re.match(r"^\s*(\d{1,4})\s*$", text)
        if m:
            return int(m.group(1))
        return None

    def _build_mapping(self, raw: list[tuple]) -> dict[int, int]:
        """从检测结果建立完整映射。"""
        total = self._doc.page_count
        if not raw:
            return {}

        # 计算每个检测点的offset
        # offset = pdf_page(0-based) - printed_page
        points = [(pdf_page, printed, pdf_page - printed) for pdf_page, printed in raw]

        # 找出主要offset
        dominant = self._find_dominant(points, total)

        # 对每个有效offset，建立映射
        mapping = {}
        for pdf_page, printed, offset in points:
            # 检查offset是否合理
            if 0 <= printed <= total and -50 <= offset <= total:
                mapping[printed] = pdf_page

        # 扩展：对缺失的页码，用主要offset补全
        max_printed = max(mapping.keys()) if mapping else total
        for printed in range(1, max_printed + 1):
            if printed not in mapping:
                # 找最近的已知offset推算
                predicted = printed + dominant
                if 0 <= predicted < total:
                    mapping[printed] = predicted

        return mapping

    def _find_dominant(self, points: list[tuple], total: int) -> int:
        """找最主要且可靠的offset值。"""
        # 收集所有offset，过滤极端值
        counter = Counter()
        for _, _, offset in points:
            if -20 <= offset <= total:
                counter[offset] += 1
        if not counter:
            return 0
        most = counter.most_common(5)
        # 筛选出现>=3次的offset中最合理的
        for offset, count in most:
            if count >= 3:
                return offset
        return most[0][0]
