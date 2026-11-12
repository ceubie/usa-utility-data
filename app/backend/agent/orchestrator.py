"""Run tool calls until the model answers, and stream the events."""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Iterator
from threading import Lock

from app.backend.agent.llm_client import (
    LLMConfigurationError,
    TextDelta,
    ToolCall,
    stream_completion,
)
from app.backend.agent.prompts import system_prompt
from app.backend.agent.tools import ToolContext, run_tool, tool_schemas
from app.backend.settings import Settings, repository_root

_LOG_LOCK = Lock()


def sse(event: str, data: object) -> str:
    """Return one server-sent event."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def orchestrate(question: str, ctx: ToolContext) -> Iterator[str]:
    """Send messages and tools until the model answers or the round cap is reached."""
    started = time_now()
    log: dict[str, object] = {
        "question": question,
        "tool_calls": [],
        "queries": [],
        "row_counts": [],
        "timings": [],
        "answer": "",
    }
    messages: list[dict] = [
        {"role": "system", "content": system_prompt(ctx.card)},
        {"role": "user", "content": question},
    ]
    tools = tool_schemas()
    try:
        yield sse("status", {"message": "Starting"})
        for round_index in range(ctx.settings.max_tool_rounds):
            yield sse("status", {"message": f"Model round {round_index + 1}"})
            text: list[str] = []
            calls: list[ToolCall] = []
            try:
                for piece in stream_completion(messages, tools, ctx.settings):
                    if isinstance(piece, TextDelta):
                        text.append(piece.text)
                        yield sse("answer_delta", {"text": piece.text})
                    elif isinstance(piece, ToolCall):
                        calls.append(piece)
            except LLMConfigurationError as exc:
                log["error"] = str(exc)
                log["missing"] = exc.missing
                yield sse("error", {"message": str(exc), "missing": exc.missing})
                return
            except RuntimeError as exc:
                log["error"] = str(exc)
                yield sse("error", {"message": str(exc)})
                return
            if not calls:
                answer = "".join(text)
                log["answer"] = answer
                yield sse("done", {"answer": answer})
                return
            messages.append(_assistant_message(text, calls, round_index))
            for index, call in enumerate(calls):
                call_id = call.call_id or f"call_{round_index}_{index}"
                arguments = _arguments(call.arguments)
                yield sse("tool_call", {"call_id": call_id, "name": call.name, "arguments": arguments})
                outcome = run_tool(call.name, call.arguments or "{}", ctx)
                yield sse("tool_result", {"call_id": call_id, "name": call.name, "result": outcome.result})
                if outcome.display is not None:
                    yield sse("display", {"call_id": call_id, "name": call.name, **outcome.display})
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(outcome.result, ensure_ascii=False, default=str),
                })
                recorded = log["tool_calls"]
                if isinstance(recorded, list):
                    recorded.append({"name": call.name, "arguments": arguments, "elapsed_s": outcome.elapsed_s})
                if outcome.query:
                    queries = log["queries"]
                    if isinstance(queries, list):
                        queries.append(outcome.query)
                if outcome.row_count is not None:
                    counts = log["row_counts"]
                    if isinstance(counts, list):
                        counts.append({"name": call.name, "row_count": outcome.row_count})
                timings = log["timings"]
                if isinstance(timings, list):
                    timings.append({"name": call.name, "elapsed_s": outcome.elapsed_s})
        message = "The ask agent stopped after the maximum number of tool rounds."
        log["error"] = message
        yield sse("error", {"message": message})
    finally:
        log["elapsed_s"] = round(time_now() - started, 4)
        append_log(log, ctx.settings)


def append_log(record: dict, settings: Settings | None = None) -> None:
    """Append one JSON line for the request. The API key is not written."""
    day = dt.date.today().isoformat()
    path = repository_root() / "logs" / "agent" / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, ensure_ascii=False, default=str)
    secret = ""
    if settings is not None:
        secret = (settings.azure_openai_api_key or "").strip()
    if len(secret) >= 8:
        payload = payload.replace(secret, "[redacted]")
    with _LOG_LOCK, path.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")


def time_now() -> float:
    return time.perf_counter()


def _assistant_message(text: list[str], calls: list[ToolCall], round_index: int) -> dict:
    response_id = next((call.response_id for call in calls if call.response_id), None)
    msg: dict = {
        "role": "assistant",
        "content": "".join(text) or None,
        "tool_calls": [
            {
                "id": call.call_id or f"call_{round_index}_{index}",
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments or "{}"},
            }
            for index, call in enumerate(calls)
        ],
    }
    if response_id:
        msg["response_id"] = response_id
    return msg


def _arguments(raw: str) -> object:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return parsed
