"""真实端到端冒烟：真实 LLM(商汤) + 真实地图(高德) + SQLite，直跑编排 graph。

用法：conda activate yk-agent && python scripts/smoke_e2e.py "想去大理玩2天"
不走 HTTP，直接以 TripState 驱动 graph.astream，逐节点打印，便于定位阻塞点。
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback


async def main(message: str) -> int:
    from yk_agent.api.state import build_default_state, profile_to_dict

    state = await build_default_state()
    print("[setup] store + graph ready")
    profile = await state.profile_repo.get("smoke-user")
    graph_state = {
        "session_id": "smoke-session",
        "user_id": "smoke-user",
        "user_message": message,
        "user_profile": profile_to_dict(profile),
    }

    findings: dict = {}
    final_answer = None
    try:
        async for update in state.graph.astream(graph_state, stream_mode="updates"):
            for name, data in update.items():
                focus = (
                    (data.get("final_answer") or data.get("plan") or "{}")
                    if isinstance(data, dict)
                    else "{}"
                )
                print(f"[node] {name}: {json.dumps(focus, ensure_ascii=False)[:200]}")
                if name in ("poi-agent", "route-agent", "budget-agent") and data.get("findings"):
                    findings.update(data["findings"])
                if isinstance(data, dict) and data.get("final_answer"):
                    final_answer = data["final_answer"]
    except Exception as e:  # noqa: BLE001
        print("[error] 编排失败:", e)
        traceback.print_exc()
        return 1

    if state.store is not None:
        await state.store.close()  # 收尾关闭连接，避免 aiosqlite 后台线程在事件循环关闭后报错

    print("\n==== 编排结果 ====")
    print("final_answer:", (final_answer or "")[:300])
    print("findings keys:", list(findings.keys()) if findings else "（无子智能体派发）")
    return 0


if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "想去大理玩2天，预算1500，不想爬山"
    sys.exit(asyncio.run(main(msg)))
