"""Model client. The provider SDK is called only when all required settings are present."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass

from openai import AzureOpenAI, OpenAIError

from app.backend.settings import Settings

_LOG = logging.getLogger(__name__)


class LLMConfigurationError(Exception):
    """The model cannot be called because a setting is missing."""

    def __init__(self, message: str, missing: list[str]) -> None:
        super().__init__(message)
        self.missing = missing


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str
    response_id: str | None = None


def _as_response_tools(tools: list[dict]) -> list[dict]:
    """Flatten Chat Completions tool schemas into Responses API function tools."""
    converted: list[dict] = []
    for tool in tools:
        fn = tool.get("function") if tool.get("type") == "function" else None
        if not isinstance(fn, dict):
            converted.append(tool)
            continue
        item: dict = {
            "type": "function",
            "name": fn["name"],
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            "strict": False,
        }
        desc = fn.get("description")
        if isinstance(desc, str) and desc:
            item["description"] = desc
        converted.append(item)
    return converted


def _prepare_responses_input(messages: list[dict]) -> tuple[str, list[dict], str | None]:
    """Extract system instructions, current round input items, and previous_response_id."""
    instructions_parts: list[str] = []
    last_assistant_idx = -1
    previous_response_id: str | None = None
    for idx, msg in enumerate(messages):
        role = msg.get("role")
        if role == "system" and isinstance(msg.get("content"), str):
            instructions_parts.append(msg["content"])
        elif role == "assistant" and msg.get("response_id"):
            last_assistant_idx = idx
            previous_response_id = str(msg["response_id"])
    instructions = "\n\n".join(instructions_parts)
    if previous_response_id and last_assistant_idx >= 0:
        outputs: list[dict] = []
        for msg in messages[last_assistant_idx + 1 :]:
            if msg.get("role") == "tool":
                outputs.append({
                    "type": "function_call_output",
                    "call_id": str(msg.get("tool_call_id") or ""),
                    "output": str(msg.get("content") or "{}"),
                })
        return instructions, outputs, previous_response_id
    inputs: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        if role in ("user", "assistant") and isinstance(msg.get("content"), str) and msg["content"]:
            inputs.append({"role": role, "content": msg["content"]})
    return instructions, inputs, None


def stream_completion(
    messages: list[dict],
    tools: list[dict],
    settings: Settings,
) -> Iterator[TextDelta | ToolCall]:
    """Yield text pieces and completed tool calls via Azure OpenAI Responses API."""
    missing = settings.missing_llm()
    if missing:
        names = ", ".join(missing)
        raise LLMConfigurationError(f"Ask is not configured. Missing {names}.", missing)
    try:
        client = AzureOpenAI(
            azure_endpoint=str(settings.azure_openai_endpoint),
            api_key=str(settings.azure_openai_api_key),
            api_version=str(settings.azure_openai_api_version),
        )
        instructions, input_items, previous_response_id = _prepare_responses_input(messages)
        kwargs: dict = {
            "model": str(settings.azure_openai_deployment),
            "input": input_items,
            "instructions": instructions,
            "tools": _as_response_tools(tools),
            "stream": True,
            "store": True,
        }
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id
        stream = client.responses.create(**kwargs)
        for event in stream:
            event_type = getattr(event, "type", "")
            if event_type in ("response.output_text.delta", "response.refusal.delta"):
                delta = getattr(event, "delta", "") or ""
                if delta:
                    yield TextDelta(str(delta))
                continue
            if event_type in ("error", "response.failed"):
                raise RuntimeError("The model request failed.")
            if event_type in ("response.completed", "response.incomplete"):
                response = getattr(event, "response", None)
                resp_id = getattr(response, "id", None)
                for item in getattr(response, "output", None) or []:
                    if getattr(item, "type", None) == "function_call":
                        call_id = str(getattr(item, "call_id", None) or getattr(item, "id", "") or "")
                        yield ToolCall(
                            call_id=call_id,
                            name=str(getattr(item, "name", None) or ""),
                            arguments=str(getattr(item, "arguments", None) or "{}"),
                            response_id=str(resp_id) if resp_id else None,
                        )
    except OpenAIError as exc:
        _LOG.exception("Azure OpenAI request failed")
        raise RuntimeError("The model request failed.") from exc
