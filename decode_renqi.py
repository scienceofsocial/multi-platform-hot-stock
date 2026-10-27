# -*- coding: utf-8 -*-
"""解码 人气交叉.html 中被 base64 + XOR 保护的页面内容。"""
import base64
import json
import os
import re

# 所有输入/输出都在本脚本所在目录，随目录整体搬迁无需改路径
DIR = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(DIR, "人气交叉.html")

with open(HTML, "r", encoding="utf-8") as f:
    src = f.read()

kf = re.search(r"_kf=(\[[^\]]*\])", src).group(1)
pc = re.search(r"_pc=(\[.*?\]);", src, re.S).group(1)

key = "".join(json.loads(kf))
parts = json.loads(pc)
raw = base64.b64decode("".join(parts))

out = bytearray()
for i, b in enumerate(raw):
    out.append(b ^ ord(key[i % len(key)]))

decoded = out.decode("utf-8")

with open(os.path.join(DIR, "_renqi_decoded.html"), "w", encoding="utf-8") as f:
    f.write(decoded)

print("key:", key)
print("decoded length:", len(decoded))
print(decoded[:3000])
