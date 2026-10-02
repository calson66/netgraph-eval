"""One small wrapper around the LLM API, so the rest of the code never touches a provider SDK.

- Messages use a neutral format (see `chat` docstring); this file converts to Anthropic or OpenAI
  format (the OpenAI path also serves OpenAI-compatible APIs such as DeepSeek).
- Every call returns token usage, latency and cost (prices from configs/pricing.yaml).
- Switching model or provider = edit configs/models.yaml, no code change.
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"


def load_config(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text())


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    model: str = ""


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = load_config("pricing.yaml")["models"].get(model)
    if prices is None:
        return 0.0  # unknown model: report 0 rather than guess; add it to pricing.yaml
    return (input_tokens * prices["input_per_mtok"]
            + output_tokens * prices["output_per_mtok"]) / 1_000_000


def chat(messages: list[dict], system: str = "", tools: list[dict] | None = None,
         model: str | None = None) -> LLMResponse:
    """Send one request.

    messages (neutral format):
      {"role": "user", "content": str}
      {"role": "assistant", "content": str | None, "tool_calls": [ToolCall, ...]}
      {"role": "tool", "tool_call_id": str, "content": str}
    tools: [{"name": str, "description": str, "parameters": <JSON schema>}]
    """
    cfg = load_config("models.yaml")
    model = model or cfg["models"]["main"]
    start = time.perf_counter()
    provider = cfg["providers"][cfg["provider"]]
    if provider["sdk"] == "anthropic":
        resp = _chat_anthropic(messages, system, tools, model, cfg["defaults"], provider)
    elif provider["sdk"] == "openai":  # OpenAI itself, or an OpenAI-compatible API like DeepSeek
        resp = _chat_openai(messages, system, tools, model, cfg["defaults"], provider)
    else:
        raise ValueError(f"unknown sdk {provider['sdk']}")
    resp.latency_ms = int((time.perf_counter() - start) * 1000)
    resp.model = model
    resp.cost_usd = cost_usd(model, resp.input_tokens, resp.output_tokens)
    return resp


# ---------- Anthropic ----------

def to_anthropic_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            blocks = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls", []):
                blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.args})
            out.append({"role": "assistant", "content": blocks})
        elif m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"],
                     "content": m["content"]}
            # Anthropic wants all tool results for one turn inside a single user message.
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


def _chat_anthropic(messages, system, tools, model, defaults, provider) -> LLMResponse:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ[provider["api_key_env"]])
    kwargs = {"model": model, "max_tokens": defaults["max_tokens"],
              "temperature": defaults["temperature"],
              "messages": to_anthropic_messages(messages)}
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = [{"name": t["name"], "description": t["description"],
                            "input_schema": t["parameters"]} for t in tools]
    r = client.messages.create(**kwargs)
    text = "".join(b.text for b in r.content if b.type == "text") or None
    calls = [ToolCall(b.id, b.name, b.input) for b in r.content if b.type == "tool_use"]
    return LLMResponse(text, calls, r.usage.input_tokens, r.usage.output_tokens)


# ---------- OpenAI ----------

def to_openai_messages(messages: list[dict], system: str) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}] if system else []
    for m in messages:
        if m["role"] == "assistant":
            msg = {"role": "assistant", "content": m.get("content")}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.name, "arguments": json.dumps(tc.args)}}
                    for tc in m["tool_calls"]
                ]
            out.append(msg)
        else:
            out.append(dict(m))
    return out


def _parse_args(raw: str | None) -> dict:
    # Malformed tool arguments are passed on (not raised) so the agent can report the error.
    try:
        args = json.loads(raw or "{}")
        return args if isinstance(args, dict) else {"_raw": raw}
    except json.JSONDecodeError:
        return {"_raw": raw}


def _chat_openai(messages, system, tools, model, defaults, provider) -> LLMResponse:
    import openai

    client = openai.OpenAI(api_key=os.environ[provider["api_key_env"]],
                           base_url=provider.get("base_url"))
    # `max_tokens` (not `max_completion_tokens`) because OpenAI-compatible APIs accept it.
    kwargs = {"model": model, "max_tokens": defaults["max_tokens"],
              "temperature": defaults["temperature"],
              "messages": to_openai_messages(messages, system)}
    if tools:
        kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
    if provider.get("extra_body"):
        kwargs["extra_body"] = provider["extra_body"]
    r = client.chat.completions.create(**kwargs)
    msg = r.choices[0].message
    calls = [ToolCall(tc.id, tc.function.name, _parse_args(tc.function.arguments))
             for tc in (msg.tool_calls or [])]
    return LLMResponse(msg.content, calls, r.usage.prompt_tokens, r.usage.completion_tokens)
