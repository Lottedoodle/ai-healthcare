"""CLI entry — delegates to backend agent graph."""

from backend.agent.graph import (
    MODE_LABELS,
    build_graph,
    format_agent_result,
    fresh_state,
    next_agent_state,
)

if __name__ == "__main__":
    print("=" * 60)
    print("🩺 Medical Triage Assistant — พิมพ์ข้อความของคุณ (พิมพ์ 'exit' เพื่อออก)")
    print("=" * 60)

    app = build_graph()
    state = fresh_state()

    while True:
        user_input = input("\nคุณ: ")
        if user_input.lower() in ("exit", "quit", "ออก"):
            print("👋 ลาก่อน!")
            break

        state["user_input"] = user_input
        result = app.invoke(state)
        payload = format_agent_result(result)

        mode_tag = f"/{payload['route_mode_label']}" if payload["route_mode_label"] else ""
        print(f"\n🤖 Assistant:", end=" ")
        if payload["awaiting_user"]:
            print(f"[{payload['intent']}] {payload['content']}")
        else:
            print(f"[{payload['intent']}{mode_tag}] {payload['content']}")
            if payload["route_reason"]:
                print(f"↳ route: {payload['route_reason']}")
            if payload["plan_summary"]:
                print(f"\n📋 Plan: {payload['plan_summary']}")
            if payload["audit_log"]:
                print("\n📋 Audit log:")
                for line in payload["audit_log"]:
                    print(f"  • {line}")

        state = next_agent_state(result)
