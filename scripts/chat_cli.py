"""Interactive text chat in the terminal (mock LLM without a key, real model with one).

Usage:  .venv/bin/python -m scripts.chat_cli [--mock]
"""
import asyncio
import json
import secrets
import sys

from app.chat import chat


async def main(force_mock: bool):
    sid = "cli" + secrets.token_hex(3)
    print("Kumbh Sahayak (text). Type in Hindi / Marathi / English. Ctrl+C to quit.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        out = await chat(sid, text, force_mock=force_mock)
        for c in out["tool_calls"]:
            print(f"  [tool] {c['name']} {json.dumps(c['args'], ensure_ascii=False)} -> ok={c['result'].get('ok')}")
        print(f"sahayak ({out['mode']}, {out['language']})> {out['reply']}")


if __name__ == "__main__":
    asyncio.run(main("--mock" in sys.argv))
