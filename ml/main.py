"""CLI-болталка с агентом (для быстрой проверки без веб-морды).

    uv run python main.py
"""

import asyncio
import uuid

from llama_index.core.agent.workflow import AgentStream, ToolCall, ToolCallResult
from llama_index.core.workflow import Context

from rag import agent, langfuse, propagate_attributes


async def _run_turn(ctx: Context, user_input: str) -> str:
    handler = agent.run(user_msg=user_input, ctx=ctx)
    answer = ""
    async for event in handler.stream_events():
        if isinstance(event, ToolCall):
            print(f"\n  → {event.tool_name}({event.tool_kwargs})")
        elif isinstance(event, ToolCallResult):
            output = event.tool_output.content if event.tool_output is not None else ""
            preview = output.strip().splitlines()
            head = preview[0] if preview else ""
            print(f"  ← {event.tool_name}: {head[:120]}{'…' if len(output) > 120 else ''}")
        elif isinstance(event, AgentStream) and event.delta and not event.tool_calls:
            print(event.delta, end="", flush=True)
            answer += event.delta
    await handler
    print("\n")
    return answer


async def main() -> None:
    print("Агент по мануалам Портала поставщиков. Введите 'выход' или 'exit' для завершения.\n")
    ctx = Context(agent)
    session_id = uuid.uuid4().hex

    while True:
        try:
            user_input = input("Вы: ").strip()
        except EOFError:
            break
        if not user_input:
            continue
        if user_input.lower() in ("выход", "exit", "quit"):
            print("До свидания!")
            break

        if langfuse is None:
            await _run_turn(ctx, user_input)
            continue

        with langfuse.start_as_current_observation(
            as_type="agent", name="chat-response", input=user_input
        ) as root:
            with propagate_attributes(trace_name="chat-response", session_id=session_id):
                answer = await _run_turn(ctx, user_input)
            root.update(output=answer)

    if langfuse is not None:
        langfuse.flush()


if __name__ == "__main__":
    asyncio.run(main())
