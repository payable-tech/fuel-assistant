# Claude through the Claude Agent SDK, signed in with this PC's Claude Code login (the plan, not API billing), the way
# bob-agent runs it. One task: the instructions, what the agent is shown (text and photos) and its tools, served
# in-process. None of Claude Code's own tools (files, shell, web) and none of this PC's Claude Code settings, hooks or
# CLAUDE.md files: only the tools given. Each run leaves a trace: what Claude thought (as a summary), which tools it
# used and what it wrote, in the order it happened.
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ResultMessage, SdkMcpTool, TextBlock, ThinkingBlock,
                              ToolUseBlock, create_sdk_mcp_server, query)

from features.cards import settings

SERVER = "fuel"              # the tool server's name: Claude sees its tools as mcp__fuel__<tool>
MAX_TURNS = 12               # a run that goes past either limit stops and says so, rather than running on
MAX_COST_USD = 2.0
PHOTO_LIMIT_BYTES = 5_000_000  # Claude refuses a larger picture
# The kinds of step in a run's trace: a summary of its thinking, a tool it used (by name), words it wrote.
THOUGHT, USED, SAID = "thought", "used", "said"


# One of the agent's tools: its name, what it does (what Claude reads), its inputs as JSON schema, and what it runs
# with its arguments (it returns a tool answer: `answer`).
@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict
    run: Callable[[dict], Awaitable[dict]]


# What came of one run: Claude's last words, why it stopped early ("" when it finished normally), its cost, and its
# trace: each step as (kind, text), in order.
@dataclass(frozen=True)
class Answer:
    text: str
    problem: str
    cost_usd: float | None
    trace: tuple[tuple[str, str], ...] = ()


# Lets Claude work on one task with the given tools, in `workspace` (where the SDK keeps the run's conversation).
async def run(system: str, text: str, photos: list[bytes], tools: list[Tool], workspace: Path) -> Answer:
    workspace.mkdir(parents=True, exist_ok=True)
    server = create_sdk_mcp_server(SERVER, tools=[SdkMcpTool(t.name, t.description, t.schema, t.run) for t in tools])
    options = ClaudeAgentOptions(
        system_prompt=system, model=settings.AGENT_MODEL, effort=settings.AGENT_EFFORT,
        thinking={"type": "adaptive", "display": "summarized"},  # its thinking comes back as text, for the trace
        tools=[], mcp_servers={SERVER: server}, strict_mcp_config=True,
        allowed_tools=[f"mcp__{SERVER}__{t.name}" for t in tools],
        permission_mode="dontAsk",  # a tool not allowed above is refused, never asked about
        setting_sources=[], max_turns=MAX_TURNS, max_budget_usd=MAX_COST_USD, cwd=workspace)
    result, trace = None, []
    async for message in query(prompt=_message(text, photos), options=options):
        if isinstance(message, AssistantMessage):
            trace += _steps(message)
        if isinstance(message, ResultMessage):
            result = message
    if result is None:
        return Answer("", "Claude stopped without an answer", None, tuple(trace))
    problem = "" if not result.is_error and result.subtype == "success" else \
        "; ".join([result.subtype, *(result.errors or [])])
    return Answer(result.result or "", problem, result.total_cost_usd, tuple(trace))


# The steps in one message of Claude's, for the trace: its thinking, the tools it asked for (by our names), its words.
def _steps(message: AssistantMessage) -> list[tuple[str, str]]:
    steps = []
    for block in message.content:
        if isinstance(block, ThinkingBlock) and block.thinking.strip():
            steps.append((THOUGHT, block.thinking.strip()))
        elif isinstance(block, ToolUseBlock):
            steps.append((USED, block.name.removeprefix(f"mcp__{SERVER}__")))
        elif isinstance(block, TextBlock) and block.text.strip():
            steps.append((SAID, block.text.strip()))
    return steps


# A tool's answer as Claude takes it: a line of text, or the reason the tool could not do it.
def answer(text: str, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "is_error": error}


# The one message Claude is given: the photos it can see (JPEG, newest last), then the text.
async def _message(text: str, photos: list[bytes]):
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(p).decode()}}
               for p in photos if len(p) <= PHOTO_LIMIT_BYTES]
    content.append({"type": "text", "text": text})
    yield {"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None}
