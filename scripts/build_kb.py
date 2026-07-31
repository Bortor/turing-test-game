"""从萌娘百科（Moegirlpedia）构建本地梗知识库。

流程：种子关键词 -> opensearch API -> 筛选匹配词条 -> extracts API ->
保存结构化 JSON。萌娘百科屏蔽了 MediaWiki 分类 API，因此通过搜索驱动词条发现。

用法：
    python build_kb.py                     # 全量构建到 data/memes.json
    python build_kb.py --merge notes.md    # 构建后合并外部 Markdown 笔记
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://zh.moegirl.org.cn/api.php"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "memes.json"

# Core meme keywords covering common categories seen in Turing-test chats.
SEEDS = [
    # 缩写/谐音
    "yyds", "awsl", "xswl", "yysy", "u1s1", "zqsg", "dbq", "xdm", "szd",
    "gkd", "kskbl", "尊嘟假嘟", "栓Q", "泰裤辣", "绝绝子", "集美",
    # 网络流行语
    "老六", "显眼包", "搭子", "i人e人", "City不City", "已老实求放过",
    "大香蕉", "浇给", "南方小土豆", "曼波", "鼠鼠", "牛马", "班味",
    "偷感", "破防", "绷不住了", "蚌埠住了", "典中典", "乐", "难绷",
    "抽象", "魔怔", "贵物", "流汗黄豆", "急", "孝", "典",
    # 游戏/VTB
    "结晶", "塔菲", "DD", "单推", "VTB", "虚拟主播", "瓦罗兰特",
    "原神启动", "赤石", "康神开播", "开盒", "赛博",
    # 弹幕/行为
    "前方高能", "一键三连", "下次一定", "梦幻联动", "要素过多",
    "键盘侠", "杠精", "二极管", "理中客", "举报", "网暴",
    # 情感/梗角色
    "吃瓜群众", "柠檬精", "打工人", "内卷", "躺平", "摆烂",
    "emo", "破大防", "小丑", "舔狗", "渣男", "绿茶",
    # 扩充：短视频/社交
    "芭比Q", "家人们", "谁懂啊", "一整个爱住", "精神内耗", "45度人生",
    "已读不回", "秒回", "查户口", "网恋", "面基", "欧皇", "非酋",
    "氪金", "开黑", "带飞", "躺赢", "摸鱼", "狗头", "裂开", "捂脸",
    "抽象话", "华语乐坛", "跪族", "集美们", "无语子", "栓Q", "绝了",
    # 扩充：游戏圈黑话
    "电子竞技", "上分", "掉分", "青铜", "王者荣耀", "吃鸡", "开挂",
    "挂机", "白给", "老玩家", "萌新", "肝", "氪", "爆率", "保底",
    "扭蛋", "抽卡", "出货", "沉船", "欧气", "毒奶", "Flag",
    # 补充：弹幕/贴吧高频
    "绷不住", "蚌埠住了", "乐子人", "带节奏", "节奏", "拱火", "串子",
    "魔怔人", "开团", "洗地", "控评", "养蛊", "切割", "背刺", "引战",
    "钓鱼", "钓鱼执法", "挂人", "小作文", "带带大师兄", "孙笑川",
    "抽象圣经", "流汗", "绷", "乐", "典", "孝", "急", "破防了",
    # 补充：饭圈/社交
    "塌房", "粉丝", "唯粉", "团粉", "路人粉", "黑粉", "脱粉", "回踩",
    "应援", "打榜", "控评", "反黑", "站姐", "私生饭", "毒唯",
]

HEADERS = {"User-Agent": UA}


def api(params: dict, retries: int = 2) -> dict:
    query = urllib.parse.urlencode(params)
    url = f"{BASE}?{query}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            if attempt == retries - 1:
                print(f"  ! api failed for {params.get('action')}: {exc}", file=sys.stderr)
                return {}
            time.sleep(2)
    return {}


def search_titles(seed: str, limit: int = 5) -> list[str]:
    data = api(
        {
            "action": "opensearch",
            "search": seed,
            "limit": limit,
            "format": "json",
        }
    )
    if not data or len(data) < 2:
        return []
    titles = data[1]
    result = []
    for t in titles:
        if seed.lower() not in t.lower() and t.lower() not in seed.lower():
            continue
        # 过滤消歧义噪音：歌曲/角色/专辑/人物/虚拟歌手等非梗词条
        if any(
            marker in t
            for marker in ["(歌曲)", "(角色)", "(专辑)", "(人物)", "(音乐)", "(游戏)", "(歌手)"]
        ):
            continue
        if len(t) > 24:  # 超长标题多半是普通条目
            continue
        result.append(t)
    return result[:3]


def fetch_extract(title: str) -> str:
    data = api(
        {
            "action": "query",
            "prop": "extracts",
            "exintro": 1,
            "explaintext": 1,
            "titles": title,
            "format": "json",
        }
    )
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        return page.get("extract", "")
    return ""


def load_notes(path: Path) -> dict[str, str]:
    """解析外部 Markdown 笔记（## 关键词 + 正文）为 {keyword: content}。"""
    result: dict[str, str] = {}
    if not path.exists():
        print(f"  ! 笔记文件不存在: {path}", file=sys.stderr)
        return result
    current_key: str | None = None
    current_lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith("## "):
            if current_key:
                result[current_key] = "\n".join(current_lines).strip()
            current_key = raw[3:].strip()
            current_lines = []
        elif current_key:
            current_lines.append(raw)
    if current_key:
        result[current_key] = "\n".join(current_lines).strip()
    return result


def build(merge_file: Path | None = None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict] = {}
    if OUT.exists():
        existing = json.loads(OUT.read_text(encoding="utf-8"))

    collected: dict[str, dict] = dict(existing)

    def save() -> None:
        OUT.write_text(
            json.dumps(collected, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    save()  # initialize file
    for seed in dict.fromkeys(SEEDS):
        print(f"[{seed}]", flush=True)
        titles = search_titles(seed)
        for title in titles:
            if title in collected:
                continue
            extract = fetch_extract(title)
            time.sleep(0.3)  # be polite to the wiki
            if not extract:
                continue
            collected[title] = {
                "title": title,
                "keywords": [seed],
                "summary": extract[:800],
                "source": "moegirl",
            }
            print(f"  + {title} ({len(extract)} chars)", flush=True)
            time.sleep(0.3)
        save()  # incremental: keep progress on interruption

    # 可选：合并外部笔记
    if merge_file is not None:
        for key, content in load_notes(merge_file).items():
            title = key.split("—")[0].strip() or key
            if title in collected:
                collected[title]["keywords"] = list(
                    dict.fromkeys(collected[title]["keywords"] + [k for k in key.split() if k])
                )
                collected[title]["summary"] += "\n\n[外部笔记]\n" + content[:600]
            else:
                collected[title] = {
                    "title": title,
                    "keywords": [key],
                    "summary": content[:800],
                    "source": "notes",
                }

    OUT.write_text(
        json.dumps(collected, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\nTotal entries: {len(collected)} -> {OUT}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="从萌娘百科构建梗知识库")
    parser.add_argument(
        "--merge",
        metavar="FILE",
        type=Path,
        default=None,
        help="可选：合并外部 Markdown 笔记（## 关键词 + 正文）到知识库",
    )
    args = parser.parse_args()
    build(args.merge)
