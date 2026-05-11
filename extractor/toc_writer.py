import json

import pymupdf


class TocWriter:
    def write(self, input_path: str, output_path: str, toc: list[dict]):
        """将TOC列表写入PDF outline。"""
        doc = pymupdf.open(input_path)
        toc_list = []
        for entry in toc:
            if entry.get("unmatched"):
                continue
            page_1based = (entry["page"] or 0) + 1
            toc_list.append([entry["level"], entry["title"], page_1based])

        doc.set_toc(toc_list)
        doc.save(output_path)
        doc.close()

    def write_from_json(self, input_path: str, toc_json_path: str, output_path: str):
        """从JSON文件读取TOC并写入PDF。"""
        with open(toc_json_path, "r", encoding="utf-8") as f:
            toc = json.load(f)
        self.write(input_path, output_path, toc)
