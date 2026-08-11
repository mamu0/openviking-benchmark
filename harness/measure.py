#!/usr/bin/env python3
"""Measurement harness for cross-session memory retrieval with OpenViking.

Runs three independent arms for each fact:

  seed     a session receives the fact and stores it via the `remember` tool
  cold     a new, isolated session answers the question with access to OpenViking
  control  a new, isolated session answers the same question with no memory at all

Only the cold phase and the control arm are measured. The reported input
tokens are the ones actually processed, i.e. net of the portion served from
cache (`prompt_tokens_details.cached_tokens`), which is reported separately.

Usage:
    python harness/measure.py seed
    python harness/measure.py cold
    python harness/measure.py control
    python harness/measure.py report
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
FACTS = json.loads((ROOT / "facts.json").read_text())
RESULTS = ROOT / "results.json"

OV_MCP = os.environ.get("OV_MCP_URL", "http://127.0.0.1:1933/mcp")
API_BASE = os.environ["AZURE_OPENAI_BASE"]
API_KEY = os.environ["AZURE_OPENAI_KEY"]
MODEL = os.environ.get("AZURE_OPENAI_MODEL", "gpt-5-mini")

# Azure OpenAI prices for gpt-5-mini, USD per 1M tokens. Source noted in the README.
PRICE_IN = float(os.environ.get("PRICE_IN_PER_M", "0.25"))
PRICE_CACHED = float(os.environ.get("PRICE_CACHED_PER_M", "0.025"))
PRICE_OUT = float(os.environ.get("PRICE_OUT_PER_M", "2.00"))

# Only the memory read tools: the cold arm must not be able to write.
COLD_TOOLS = {"recall", "find", "read", "list", "grep", "glob"}
SEED_TOOLS = {"remember"}

SYS_COLD = (
    "You are a technical assistant. Before answering you must ALWAYS consult the "
    "long-term memory available through the tools, because the answer depends on "
    "decisions made in previous sessions that you do not know about. If after "
    "consulting it you cannot find the information, explicitly say you don't know. "
    "Answer in English, concisely."
)
SYS_CONTROL = (
    "You are a technical assistant. Answer in English, concisely. "
    "If you don't know the requested information, explicitly say so."
)
SYS_SEED = (
    "You are a technical assistant. When you receive information to remember, "
    "store it in long-term memory using the available tool."
)


def mcp_to_openai(tool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": (tool.description or "")[:1024],
            "parameters": tool.inputSchema or {"type": "object", "properties": {}},
        },
    }


async def run_agent(system: str, user: str, allowed: set[str], max_steps: int = 6) -> dict:
    """A single isolated agent turn. Returns the answer and cumulative usage."""
    client = OpenAI(base_url=API_BASE, api_key=API_KEY)
    usage = {"in_fresh": 0, "in_cached": 0, "out": 0, "calls": 0, "tools_used": []}
    t0 = time.time()

    async with streamablehttp_client(OV_MCP) as (r, w, _):
        async with ClientSession(r, w) as mcp:
            await mcp.initialize()
            listed = await mcp.list_tools()
            tools = [mcp_to_openai(t) for t in listed.tools if t.name in allowed]

            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]

            for _ in range(max_steps):
                kwargs = dict(model=MODEL, messages=messages, max_completion_tokens=4000)
                if tools:
                    kwargs["tools"] = tools
                resp = client.chat.completions.create(**kwargs)

                u = resp.usage
                cached = (u.prompt_tokens_details.cached_tokens or 0) if u.prompt_tokens_details else 0
                usage["in_fresh"] += u.prompt_tokens - cached
                usage["in_cached"] += cached
                usage["out"] += u.completion_tokens
                usage["calls"] += 1

                msg = resp.choices[0].message
                if not msg.tool_calls:
                    usage["answer"] = msg.content or ""
                    break

                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {"id": c.id, "type": "function",
                         "function": {"name": c.function.name, "arguments": c.function.arguments}}
                        for c in msg.tool_calls
                    ],
                })
                for call in msg.tool_calls:
                    usage["tools_used"].append(call.function.name)
                    try:
                        args = json.loads(call.function.arguments or "{}")
                        out = await mcp.call_tool(call.function.name, args)
                        text = "\n".join(c.text for c in out.content if hasattr(c, "text"))
                    except Exception as exc:  # noqa: BLE001
                        text = f"ERROR: {exc}"
                    messages.append({
                        "role": "tool", "tool_call_id": call.id, "content": text[:20000],
                    })
            else:
                usage["answer"] = "(step limit reached)"

    usage["seconds"] = round(time.time() - t0, 2)
    usage["cost_usd"] = round(
        usage["in_fresh"] / 1e6 * PRICE_IN
        + usage["in_cached"] / 1e6 * PRICE_CACHED
        + usage["out"] / 1e6 * PRICE_OUT,
        6,
    )
    return usage


def graded(answer: str, expected: list[list[str]]) -> bool:
    """Weak keyword-based pre-grading, used only as an immediate signal.

    Not reliable for facts that overlap with well-known best practices, since a
    model with no memory can produce them anyway in a generic answer. The final
    verdict is the one produced by `judge`.
    """
    low = answer.lower()
    return all(any(k in low for k in group) for group in expected)


RUBRIC = (
    "You are a strict grader. You receive a specific FACT and an assistant's ANSWER.\n"
    "Reply with a single word: YES or NO.\n"
    "Reply YES only if the answer STATES the specific fact as known, organization-\n"
    "specific information.\n"
    "Reply NO if the answer is generic, lists the fact as one of several possible\n"
    "options, asks for clarification, or states it doesn't know the information.\n"
)


def judge_answer(fact: str, answer: str) -> bool:
    client = OpenAI(base_url=API_BASE, api_key=API_KEY)
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": RUBRIC},
            {"role": "user", "content": f"FACT:\n{fact}\n\nANSWER:\n{answer}"},
        ],
        max_completion_tokens=2000,
    )
    return (resp.choices[0].message.content or "").strip().upper().startswith("YES")


def load() -> dict:
    return json.loads(RESULTS.read_text()) if RESULTS.exists() else {}


def save(data: dict) -> None:
    RESULTS.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def main() -> None:
    phase = sys.argv[1] if len(sys.argv) > 1 else "report"
    data = load()

    if phase == "judge":
        for fid, f in FACTS.items():
            for arm in ("cold", "control"):
                r = data.get(fid, {}).get(arm)
                if not r:
                    continue
                r["ok"] = judge_answer(f["fact"], r["answer"])
                print(f"[judge] {fid:<4} {arm:<8} -> "
                      f"{'RETRIEVED' if r['ok'] else 'NOT RETRIEVED'}")
        save(data)
        return

    if phase == "report":
        print(f"{'fact':<6}{'arm':<10}{'outcome':<12}{'in_fresh':>9}{'cached':>8}{'out':>7}"
              f"{'calls':>10}{'sec':>7}{'USD':>10}")
        for fid in FACTS:
            for arm in ("cold", "control"):
                r = data.get(fid, {}).get(arm)
                if not r:
                    continue
                outcome = "retrieved" if r["ok"] else "failed"
                print(f"{fid:<6}{arm:<10}{outcome:<12}{r['in_fresh']:>9}{r['in_cached']:>8}"
                      f"{r['out']:>7}{r['calls']:>10}{r['seconds']:>7}{r['cost_usd']:>10.6f}")
        return

    for fid, f in FACTS.items():
        data.setdefault(fid, {})
        if phase == "seed":
            r = asyncio.run(run_agent(SYS_SEED, f"Remember this information: {f['fact']}", SEED_TOOLS))
            r["ok"] = "remember" in r["tools_used"]
            print(f"[seed]    {fid}: tool={r['tools_used']} {r['seconds']}s")
        elif phase == "cold":
            r = asyncio.run(run_agent(SYS_COLD, f["question"], COLD_TOOLS))
            r["ok"] = graded(r["answer"], f["expected"])
            print(f"[cold]    {fid}: {'RETRIEVED' if r['ok'] else 'FAILED'} "
                  f"in_fresh={r['in_fresh']} tool={r['tools_used']}\n  -> {r['answer'][:220]}\n")
        elif phase == "control":
            r = asyncio.run(run_agent(SYS_CONTROL, f["question"], set()))
            r["ok"] = graded(r["answer"], f["expected"])
            print(f"[control] {fid}: {'RETRIEVED' if r['ok'] else 'FAILED'} "
                  f"in_fresh={r['in_fresh']}\n  -> {r['answer'][:220]}\n")
        else:
            raise SystemExit(f"unknown phase: {phase}")
        data[fid][phase] = r
        save(data)


if __name__ == "__main__":
    main()
