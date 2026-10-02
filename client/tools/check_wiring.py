"""回调接线静态检查：callback= 表达式里的 self.xxx 必须在同文件有 def xxx。

用法：py -3.13 tools/check_wiring.py [client根目录]
退出码 0 = 无断线；1 = 存在缺失（打印明细）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def _expr_spans(src: str, key: str) -> list[str]:
    """提取 callback= 右侧表达式（括号配平，遇同深度逗号截止）。"""
    out: list[str] = []
    for m in re.finditer(key, src):
        j = m.end()
        depth = 0
        started = False
        while j < len(src):
            c = src[j]
            if c in "([{":
                depth += 1
                started = True
            elif c in ")]}":
                if started and depth == 0:
                    break
                depth -= 1
                if depth < 0:
                    break
            elif c == "," and depth == 0 and started:
                break
            j += 1
        out.append(src[m.end():j])
    return out


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    missing: list[tuple[str, str, str]] = []
    for p in root.rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        defs = set(re.findall(r"def ([A-Za-z_]\w*)", src))
        for expr in _expr_spans(src, r"callback="):
            for mm in re.finditer(r"self\.([A-Za-z_]\w*)", expr):
                if mm.group(1) not in defs:
                    missing.append((str(p), mm.group(1), expr.strip()[:70]))
    for f, name, expr in missing:
        print(f"BROKEN {f}: self.{name}  <- {expr}")
    print(f"check_wiring: {len(missing)} broken")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
