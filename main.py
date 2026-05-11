"""
pdf_contents_extractor — 为PDF添加目录标签（outline/bookmarks）。

用法:
    python main.py extract input.pdf -o toc.json       # 提取目录
    python main.py apply input.pdf toc.json -o out.pdf  # 应用目录
    python main.py auto input.pdf -o out.pdf            # 一步到位
"""

import argparse
import json
import sys

from extractor.pdf_reader import PdfReader
from extractor.toc_page_parser import TocPageParser
from extractor.toc_locator import TocLocator
from extractor.toc_writer import TocWriter


def cmd_extract(args):
    reader = PdfReader(args.input)
    parser = TocPageParser(max_search_pages=args.toc_search_pages)

    # 解析 --toc-pages 参数
    search_pages = None
    if args.toc_pages:
        search_pages = _parse_page_range(args.toc_pages)

    doc = reader._doc  # 获取底层 pymupdf Document
    page_num = parser.find_toc_page(doc, search_pages)

    if page_num is None:
        print("错误: 未找到目录页。可以用 --toc-pages 手动指定页码范围。")
        sys.exit(1)

    print(f"找到目录页: 第 {page_num + 1} 页")

    entries = parser.parse_entries(doc, page_num)
    print(f"解析到 {len(entries)} 条目录项")

    locator = TocLocator(reader, threshold=args.fuzzy_threshold)
    matched = locator.locate(entries)

    matched_count = sum(1 for m in matched if not m.unmatched)
    unmatched_count = sum(1 for m in matched if m.unmatched)
    print(f"定位成功: {matched_count}, 未匹配: {unmatched_count}")

    output = []
    for m in matched:
        output.append({
            "title": m.title,
            "level": m.level,
            "page": m.page,
            "unmatched": m.unmatched,
        })

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"目录已导出到: {args.output}")
    if unmatched_count > 0:
        print("提示: 有未匹配的条目，请手动编辑 JSON 文件补充页码。")

    reader.close()


def cmd_apply(args):
    writer = TocWriter()
    writer.write_from_json(args.input, args.toc, args.output)
    print(f"目录已写入: {args.output}")


def cmd_auto(args):
    reader = PdfReader(args.input)
    parser = TocPageParser()
    page_num = parser.find_toc_page(reader._doc)

    if page_num is None:
        print("错误: 未找到目录页。")
        sys.exit(1)

    print(f"找到目录页: 第 {page_num + 1} 页")
    entries = parser.parse_entries(reader._doc, page_num)
    print(f"解析到 {len(entries)} 条目录项")

    locator = TocLocator(reader)
    matched = locator.locate(entries)
    matched_count = sum(1 for m in matched if not m.unmatched)
    print(f"定位成功: {matched_count}")

    toc = []
    for m in matched:
        toc.append({
            "title": m.title,
            "level": m.level,
            "page": m.page,
            "unmatched": m.unmatched,
        })

    writer = TocWriter()
    writer.write(args.input, args.output, toc)
    print(f"目录已写入: {args.output}")

    reader.close()


def _parse_page_range(s: str) -> list[int]:
    """解析页码范围字符串，如 '1-10' 或 '3'。"""
    if "-" in s:
        start, end = s.split("-", 1)
        return list(range(int(start) - 1, int(end)))
    return [int(s) - 1]


def main():
    ap = argparse.ArgumentParser(
        description="为无目录标签的PDF添加可点击的层级书签",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    # extract
    p_extract = sub.add_parser("extract", help="从PDF提取目录，导出为JSON")
    p_extract.add_argument("input", help="输入PDF文件")
    p_extract.add_argument("-o", "--output", default="toc.json", help="输出JSON文件(默认: toc.json)")
    p_extract.add_argument("--toc-pages", help="手动指定目录页码范围(如 1-10)")
    p_extract.add_argument("--toc-search-pages", type=int, default=20, help="搜索目录页的前N页(默认: 20)")
    p_extract.add_argument("--fuzzy-threshold", type=int, default=85, help="模糊匹配阈值0-100(默认: 85)")
    p_extract.set_defaults(func=cmd_extract)

    # apply
    p_apply = sub.add_parser("apply", help="将JSON目录写入PDF")
    p_apply.add_argument("input", help="输入PDF文件")
    p_apply.add_argument("toc", help="目录JSON文件")
    p_apply.add_argument("-o", "--output", default="output.pdf", help="输出PDF文件(默认: output.pdf)")
    p_apply.set_defaults(func=cmd_apply)

    # auto
    p_auto = sub.add_parser("auto", help="一键提取并写入目录")
    p_auto.add_argument("input", help="输入PDF文件")
    p_auto.add_argument("-o", "--output", default="output.pdf", help="输出PDF文件(默认: output.pdf)")
    p_auto.set_defaults(func=cmd_auto)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
