"""Run the 10 demo conversations in text mode and check expectations (tools called, key facts present).

Usage:
  .venv/bin/python -m scripts.run_demo_conversations          # real LLM if key set, else mock
  .venv/bin/python -m scripts.run_demo_conversations --mock   # force mock LLM
"""
import asyncio
import json
import sys
import time

from app import config, memory
from app.chat import chat, detect_language

DEMOS = json.loads((config.ROOT / "app/static/demo_conversations.json").read_text(encoding="utf-8"))


async def main(force_mock: bool) -> int:
    failures = 0
    for d in DEMOS:
        print(f"\n=== Demo {d['id']}: {d['title']} ===")
        caller = d.get("caller_id") or f"c_demo{d['id']}_{int(time.time())}"
        if d.get("caller_id"):
            memory.forget(caller)  # start the memory demo clean
        sessions = d.get("sessions") or [d["turns"]]
        tools, replies, problems = [], [], []
        for n, turns in enumerate(sessions):
            sid = f"demo{d['id']}_{n}_{int(time.time())}"
            if n:
                print("  -- caller hangs up and calls again --")
                memory.end_session(prev_sid)
                memory.summarize_session(prev_sid)
            prev_sid = sid
            for i, turn in enumerate(turns):
                t0 = time.perf_counter()
                out = await chat(sid, turn, force_mock=force_mock, caller_id=caller)
                ms = int((time.perf_counter() - t0) * 1000)
                names = [c["name"] for c in out["tool_calls"]]
                if i == 0 and n == 0 and set(names) & set(d.get("expect", {}).get("first_turn_no_tools", [])):
                    problems.append(f"called {names} before asking for a landmark")
                if i == 0 and d.get("expect", {}).get("lang_turn1") and detect_language(out["reply"]) != d["expect"]["lang_turn1"]:
                    problems.append("replied in the wrong language")
                tools += names
                replies.append(out["reply"])
                print(f"  caller : {turn}")
                for c in out["tool_calls"]:
                    print(f"  tool   : {c['name']}({json.dumps(c['args'], ensure_ascii=False)[:90]}) "
                          f"ok={c['result'].get('ok')} {c['result'].get('_ms')}ms")
                print(f"  sahayak: {out['reply']}  [{out['mode']}, lang={out['language']}, {ms}ms]")
        exp = d.get("expect", {})
        missing = [t for t in exp.get("tools", []) if t not in tools]
        text = " ".join(replies)
        content_ok = not exp.get("contains_any") or any(s in text for s in exp["contains_any"])
        if exp.get("contains_all") and not all(s in text for s in exp["contains_all"]):
            problems.append(f"missing some of {exp['contains_all']}")
        bad = [s for s in exp.get("contains_none", []) if s in text]
        if bad:
            problems.append(f"contains forbidden {bad}")
        ok = not missing and content_ok and not problems
        failures += not ok
        print(f"  RESULT : {'PASS' if ok else 'FAIL'}"
              + (f" missing tools {missing}" if missing else "")
              + ("" if content_ok else f" reply lacks any of {exp['contains_any']}")
              + (" " + "; ".join(problems) if problems else ""))
    print(f"\n{len(DEMOS) - failures}/{len(DEMOS)} demos passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--mock" in sys.argv)))
