"""quick RAG smoke test against inland relay"""
import json
import re
import urllib.parse
import urllib.request

QUERIES = [
    "茅台 白酒 估值",
    "新能源车 渗透率",
    "AI 算力 半导体",
    "美联储 降息 科技股",
    "港股 南向资金",
    "腾讯 00700",
]

TOKEN = "CQ_Relay_Secure_2026_YQ"
BASE = "http://47.108.191.110:8001/relay/rag/search"

def query(q):
    url = f"{BASE}?query={urllib.parse.quote(q)}&market_type=A_STOCK&max_length=800"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

for q in QUERIES:
    print(f"\n=== {q} ===")
    try:
        d = query(q)
        text = d.get("local_results", "")
        sources = re.findall(r"\[\d+\] 来源: ([^\n]+)", text)
        for i, s in enumerate(sources[:3], 1):
            # 从路径提取文件名（跨平台）
            name = s.replace("\\", "/").split("/")[-1]
            print(f"  [{i}] {name[:80]}")
    except Exception as e:
        print(f"  ERR {e}")
