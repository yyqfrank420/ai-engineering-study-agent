# ─────────────────────────────────────────────────────────────────────────────
# File: backend/api/sse_handler.py
# Purpose: SSE endpoints — all browser↔backend communication over HTTP streaming.
#          Two POST endpoints that return Server-Sent Events streams:
#            POST /api/chat          — runs the agent pipeline
#            POST /api/node-selected — generates suggested follow-up questions
#          Security gates (payload size, rate limiting, prompt injection)
#          are applied before entering the stream.
# Language: Python
# Connects to: agent/graph.py, storage/message_store.py,
#              storage/thread_store.py, config.py, app.state (FAISS)
# Inputs:  authenticated JSON request body with thread_id + payload
# Outputs: text/event-stream with typed JSON events
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import uuid
from contextlib import suppress

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, field_validator

from adapters.supabase_auth_adapter import get_current_user
from agent.graph import run_agent
from agent.state import AgentState
from api.chat_guards import byte_len, check_prompt_injection, check_rate_limit, knowledge_base_ready
from api.node_selected_service import stream_suggested_questions
from api.sse_utils import sse, streaming_response
from agent.tools.graph_worker_tools.generate_graph_tool import generate_graph
from agent.tools.rag_worker_tools.get_section_tool import make_get_section_tool
from agent.tools.rag_worker_tools.rag_search_tool import make_rag_search_tool
from config import settings
from storage import message_store, thread_store
from storage.profile_store import upsert_profile

router = APIRouter(prefix="/api")
_search_tool_requests: dict[str, asyncio.Event] = {}


# ── Request models ─────────────────────────────────────────────────────────────

_VALID_COMPLEXITY = {"auto", "low", "prototype", "production"}
_VALID_GRAPH_MODE  = {"auto", "on", "off"}


class ChatRequest(BaseModel):
    thread_id: str
    content: str
    complexity: str = "auto"
    graph_mode: str = "auto"
    research_enabled: bool = False

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("complexity")
    @classmethod
    def validate_complexity(cls, value: str) -> str:
        if value not in _VALID_COMPLEXITY:
            return "auto"
        return value

    @field_validator("graph_mode")
    @classmethod
    def validate_graph_mode(cls, value: str) -> str:
        if value not in _VALID_GRAPH_MODE:
            return "auto"
        return value


class NodeSelectedRequest(BaseModel):
    thread_id: str
    node_id: str
    title: str
    description: str

    model_config = ConfigDict(str_strip_whitespace=True)


class SearchToolRequest(BaseModel):
    thread_id: str
    request_id: str

    model_config = ConfigDict(str_strip_whitespace=True)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat_endpoint(body: ChatRequest, request: Request, user=Depends(get_current_user)):
    """
    Run the agent pipeline and stream events back as SSE.
    Pre-flight security gates run synchronously before opening the stream.
    """
    user_id = user["id"]
    upsert_profile(user_id, user["email"] or f"{user_id}@unknown.local")
    thread_id = body.thread_id
    content = body.content
    thread = thread_store.get_thread(user_id, thread_id)
    if thread is None:
        async def _missing_thread():
            yield sse({"type": "error", "content": "Thread not found"})
        return streaming_response(_missing_thread())

    # ── Pre-flight checks (synchronous, before opening the stream) ─────────────
    if byte_len(content) > settings.max_message_bytes:
        async def _too_large():
            yield sse({"type": "error", "content": "Message too large (max 2KB)"})
        return streaming_response(_too_large())

    if not content:
        async def _empty():
            yield sse({"type": "error", "content": "Empty message"})
        return streaming_response(_empty())

    limit_error = check_rate_limit(user_id)
    if limit_error:
        async def _rate_limited():
            yield sse({"type": "error", "content": limit_error})
        return streaming_response(_rate_limited())

    if not check_prompt_injection(content):
        async def _injection():
            yield sse({"type": "error", "content": "Message blocked by security filter"})
        return streaming_response(_injection())

    message_count = message_store.count_messages(user_id, thread_id)
    if message_count + 2 > settings.max_messages_per_thread:
        async def _thread_full():
            yield sse({
                "type": "error",
                "content": "Thread message limit reached. Start a new chat to continue.",
            })
        return streaming_response(_thread_full())

    if not knowledge_base_ready(request):
        async def _missing_resources():
            yield sse({
                "type": "error",
                "content": "Knowledge base is still loading. Please try again in a moment.",
            })
        return streaming_response(_missing_resources())

    # ── Build tools bound to the loaded FAISS index ────────────────────────────
    rag_search_tool  = make_rag_search_tool(request.app.state.vectorstore, request.app.state.parent_docs)
    get_section_tool = make_get_section_tool(request.app.state.parent_docs)
    rag_tools        = [rag_search_tool, get_section_tool]
    graph_tools      = [generate_graph, get_section_tool]
    node_detail_tools = [rag_search_tool]

    async def stream():
        # Queue bridges the agent (which calls send()) and the SSE generator (which yields).
        # run_agent is launched as a task; we drain the queue while it runs.
        queue: asyncio.Queue[dict] = asyncio.Queue()

        request_id = str(uuid.uuid4())

        async def send(event: dict) -> None:
            await queue.put(event)

        async def await_search_tool_request(request_id: str, timeout_s: float) -> bool:
            event = asyncio.Event()
            _search_tool_requests[request_id] = event
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout_s)
                return True
            except asyncio.TimeoutError:
                return False
            finally:
                _search_tool_requests.pop(request_id, None)

        await send({
            "type": "worker_status",
            "worker": "orchestrator",
            "status": "Question received — preparing context…",
        })

        history = message_store.get_history(user_id, thread_id, limit=settings.max_messages_per_thread)
        existing_graph = thread_store.get_graph(user_id, thread_id)
        state: AgentState = {
            "session_id":        thread_id,
            "request_id":        request_id,
            "user_message":      content,
            "history":           history,
            "complexity":        body.complexity,
            "graph_mode":        body.graph_mode,
            "research_enabled":  body.research_enabled,
            "route":             "",
            "rag_chunks":        [],
            "retrieval_relevance": "strong",
            "retrieval_notice":  "",
            "graph_data":        existing_graph,
            "graph_changed":     False,
            "graph_notice_sent": False,
            "research_context":  "",
            "response_text":     "",
            "send":              send,
            "await_search_tool_request": await_search_tool_request,
        }

        agent_task = asyncio.create_task(run_agent(state, rag_tools, graph_tools, node_detail_tools))

        try:
            # Drain queue until agent finishes AND queue is empty.
            # Short timeout on each get() so we re-check agent_task.done() frequently.
            # Hard wall-clock timeout aborts the task if it runs too long.
            loop_start = asyncio.get_event_loop().time()
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.05)
                    yield sse(event)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        agent_task.cancel()
                        return
                    if agent_task.done() and queue.empty():
                        break
                    elapsed = asyncio.get_event_loop().time() - loop_start
                    if elapsed > settings.agent_timeout_s:
                        agent_task.cancel()
                        yield sse({"type": "error", "content": "Response timed out — please try again"})
                        yield sse({"type": "done"})
                        return
        except asyncio.CancelledError:
            agent_task.cancel()
            raise
        finally:
            if agent_task.cancelled():
                with suppress(asyncio.CancelledError):
                    await agent_task

        # Surface any unhandled agent exception as an SSE error event
        if not agent_task.cancelled():
            exc = agent_task.exception()
            if exc:
                yield sse({"type": "error", "content": f"Server error: {str(exc)}"})
                return

            final_state = agent_task.result()
            title = thread["title"]
            if title == "New chat":
                title = content[:60]
            thread_store.touch_thread(user_id, thread_id, title=title)
            message_store.append(user_id, thread_id, "user", content)
            message_store.append(user_id, thread_id, "assistant", final_state["response_text"])
            if final_state.get("graph_data"):
                saved = thread_store.save_graph(user_id, thread_id, final_state["graph_data"])
                if not saved:
                    yield sse({
                        "type": "error",
                        "content": (
                            "Graph is large — it's displayed above but won't be saved. "
                            "Start a new chat to reset."
                        ),
                    })

    return streaming_response(stream())


@router.post("/chat/use-search-tool")
async def use_search_tool_endpoint(body: SearchToolRequest, user=Depends(get_current_user)):
    user_id = user["id"]
    thread = thread_store.get_thread(user_id, body.thread_id)
    if thread is None:
        return {"ok": False, "status": "thread_not_found"}

    event = _search_tool_requests.get(body.request_id)
    if event is None:
        return {"ok": False, "status": "expired"}

    event.set()
    return {"ok": True, "status": "search_requested"}


@router.post("/node-selected")
async def node_selected_endpoint(body: NodeSelectedRequest, user=Depends(get_current_user)):
    """
    Generate 3 suggested follow-up questions for a clicked graph node.
    Streams a single suggested_questions event then a done event.
    """
    user_id = user["id"]
    upsert_profile(user_id, user["email"] or f"{user_id}@unknown.local")
    thread_id = body.thread_id
    node_title = body.title
    node_description = body.description
    thread = thread_store.get_thread(user_id, thread_id)
    if thread is None:
        async def _missing_thread():
            yield sse({"type": "error", "content": "Thread not found"})
            yield sse({"type": "done"})
        return streaming_response(_missing_thread())

    if not body.node_id:
        async def _missing_node():
            yield sse({"type": "error", "content": "Missing node id"})
            yield sse({"type": "done"})
        return streaming_response(_missing_node())

    if not node_title:
        async def _missing_title():
            yield sse({"type": "error", "content": "Missing node title"})
            yield sse({"type": "done"})
        return streaming_response(_missing_title())

    if byte_len(f"{node_title}\n{node_description}") > settings.max_node_text_bytes:
        async def _node_too_large():
            yield sse({"type": "error", "content": "Selected node payload too large"})
            yield sse({"type": "done"})
        return streaming_response(_node_too_large())

    limit_error = check_rate_limit(user_id)
    if limit_error:
        async def _rate_limited():
            yield sse({"type": "error", "content": limit_error})
            yield sse({"type": "done"})
        return streaming_response(_rate_limited())

    history = message_store.get_history(user_id, thread_id, limit=6)

    async def stream():
        async for event in stream_suggested_questions(node_title, node_description, history):
            yield sse(event)

    return streaming_response(stream())
