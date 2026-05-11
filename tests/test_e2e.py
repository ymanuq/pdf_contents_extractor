"""端到端测试：生成测试 PDF → 提取目录 → 应用目录 → 验证。"""
import json
import os
import sys

import pymupdf


def create_test_pdf(path: str):
    """创建一个带目录页的简单中文PDF。"""
    doc = pymupdf.open()

    toc_html = """
    <h1>目录</h1>
    <p>第一章 引言 ............... 1</p>
    <p>1.1 背景 ................. 3</p>
    <p>1.2 动机 ................ 10</p>
    <p>第二章 方法 .............. 15</p>
    <p>2.1 方案设计 ............. 18</p>
    <p>2.2 实现细节 ............. 22</p>
    <p>第三章 结论 .............. 30</p>
    """
    page = doc.new_page(width=595, height=842)
    page.insert_htmlbox((72, 72, 500, 700), toc_html)

    content_htmls = {
        0: "<h1>第一章 引言</h1><p>这是引言的内容。</p>",
        2: "<h2>1.1 背景</h2><p>这是背景介绍。</p>",
        9: "<h2>1.2 动机</h2><p>这是研究动机。</p>",
        14: "<h1>第二章 方法</h1><p>这是方法概述。</p>",
        17: "<h2>2.1 方案设计</h2><p>这是方案设计内容。</p>",
        21: "<h2>2.2 实现细节</h2><p>这是实现细节。</p>",
        29: "<h1>第三章 结论</h1><p>这是结论。</p>",
    }

    for i in range(34):
        page = doc.new_page(width=595, height=842)
        if i in content_htmls:
            page.insert_htmlbox((72, 72, 500, 700), content_htmls[i])

    doc.save(path)
    doc.close()
    print(f"测试PDF已创建: {path}")


def test_extract(pdf_path: str, json_path: str):
    """测试 extract 命令。"""
    from extractor.pdf_reader import PdfReader
    from extractor.toc_page_parser import TocPageParser
    from extractor.toc_locator import TocLocator

    reader = PdfReader(pdf_path)
    parser = TocPageParser()
    page_num = parser.find_toc_page(reader._doc)

    assert page_num is not None, "未找到目录页"
    assert page_num == 0, f"目录页应为第1页(0-based=0)，实际: {page_num}"
    print(f"✓ 目录页定位: 第 {page_num + 1} 页")

    entries = parser.parse_entries(reader._doc, page_num)
    assert len(entries) == 7, f"应解析出7条目录，实际: {len(entries)}"
    print(f"✓ 解析条目数: {len(entries)}")

    # 验证层级
    levels = [e.level for e in entries]
    assert levels[0] == 1, f"第一条应为一级标题，实际: {levels[0]}"
    print(f"✓ 层级推断: {levels}")

    locator = TocLocator(reader)
    matched = locator.locate(entries)
    matched_count = sum(1 for m in matched if not m.unmatched)
    assert matched_count >= 5, f"至少应匹配5条，实际: {matched_count}"
    print(f"✓ 正文定位: {matched_count}/7 成功")

    output = []
    for m in matched:
        output.append({
            "title": m.title,
            "level": m.level,
            "page": m.page,
            "unmatched": m.unmatched,
        })

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"✓ JSON导出: {json_path}")

    reader.close()
    return True


def test_apply(pdf_path: str, json_path: str, output_path: str):
    """测试 apply 命令。"""
    from extractor.toc_writer import TocWriter

    writer = TocWriter()
    writer.write_from_json(pdf_path, json_path, output_path)

    # 验证输出PDF有目录
    doc = pymupdf.open(output_path)
    toc = doc.get_toc()
    assert len(toc) > 0, "输出PDF应有目录"
    print(f"✓ 输出PDF目录项: {len(toc)} 条")

    # 验证页码正确
    assert toc[0][2] == 1, f"第一条目录页码应为1，实际: {toc[0][2]}"
    print(f"✓ 第一条页码正确: {toc[0][2]}")

    doc.close()
    return True


def main():
    test_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(test_dir)

    pdf_path = os.path.join(test_dir, "test_input.pdf")
    json_path = os.path.join(test_dir, "test_toc.json")
    output_path = os.path.join(test_dir, "test_output.pdf")

    create_test_pdf(pdf_path)

    sys.path.insert(0, project_root)
    test_extract(pdf_path, json_path)
    test_apply(pdf_path, json_path, output_path)

    # 清理
    for f in [pdf_path, json_path, output_path]:
        if os.path.exists(f):
            os.remove(f)

    print("\n✓✓✓ 所有测试通过！")


if __name__ == "__main__":
    main()
