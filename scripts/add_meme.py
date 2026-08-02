"""快速添加单个梗到本地知识库（毫秒级，零 API 费用）。

用法：
    python add_meme.py "梗名" "解释/用法/识别要点"

会合并进 data/memes.json（source=notes），不触发萌娘百科请求。
新增批量梗/抓取新梗才用 build_kb.py 全量重建。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "memes.json"


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    title = sys.argv[1].strip()
    summary = sys.argv[2].strip()

    data = json.loads(OUT.read_text(encoding="utf-8"))
    entry = data.get(title)
    if entry:
        # 已存在：追加 keywords + 覆盖 summary
        entry["keywords"] = list(dict.fromkeys(entry["keywords"] + [title]))
        entry["summary"] = summary
        entry["source"] = "notes"
        action = "更新"
    else:
        data[title] = {
            "title": title,
            "keywords": [title],
            "summary": summary,
            "source": "notes",
        }
        action = "新增"

    OUT.write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"{action}完成: {title}（共 {len(data)} 词条）")


if __name__ == "__main__":
    main()
