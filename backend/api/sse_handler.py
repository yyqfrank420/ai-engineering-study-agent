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
import logging
import uuid
from contextlib import suppress
import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.requests import HTTPConnection

from analytics.events import enqueue_analytics_event, output_shape_from_final_state
from adapters.supabase_auth_adapter import get_current_user
from agent.graph import run_agent
from agent.state import AgentState
from api.chat_guards import (
    byte_len,
    check_prompt_injection,
    check_rate_limit,
    internal_test_stream_scope,
    is_production_traffic,
    knowledge_base_ready,
    truncate_utf8,
)
from api.node_selected_service import stream_suggested_questions
from api.sse_utils import sse, sse_error, streaming_response
from config import settings
from storage import message_store, runtime_state_store, thread_store
from storage.errors import ThreadMessageLimitExceeded
from storage.profile_store import upsert_profile

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def _make_agent_tools(request: HTTPConnection):
    from agent.tools.graph_worker_tools.generate_graph_tool import generate_graph
    from agent.tools.rag_worker_tools.get_section_tool import make_get_section_tool
    from agent.tools.rag_worker_tools.rag_search_tool import make_rag_search_tool

    rag_search_tool = make_rag_search_tool(
        request.app.state.vectorstore, request.app.state.parent_docs
    )
    get_section_tool = make_get_section_tool(request.app.state.parent_docs)
    return (
        [rag_search_tool, get_section_tool],
        [generate_graph, get_section_tool],
        [rag_search_tool],
    )


# ── Request models ─────────────────────────────────────────────────────────────

_VALID_COMPLEXITY = {"auto", "low", "prototype", "production"}
_VALID_GRAPH_MODE = {"auto", "on", "off"}


class ChatRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=64)
    content: str
    complexity: str = "auto"
    graph_mode: str = "auto"
    research_enabled: bool = False
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

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
    thread_id: str = Field(min_length=1, max_length=64)
    node_id: str = Field(max_length=256)
    title: str = Field(max_length=1024)
    description: str = Field(max_length=4096)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class SearchToolRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=128)

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post("/chat")
async def chat_endpoint(
    body: ChatRequest, request: Request, user=Depends(get_current_user)
):
    """
    Run the agent pipeline and stream events back as SSE.
    Pre-flight security gates run synchronously before opening the stream.
    """
    user_id = user["id"]
    upsert_profile(user_id, user["email"] or f"{user_id}@unknown.local")
    thread_id = body.thread_id
    content = body.content
    request_state = getattr(request, "state", None)
    if request_state is not None:
        request_state.thread_id = thread_id
        request_state.client_request_id = body.client_request_id
    request_id = getattr(request_state, "request_id", str(uuid.uuid4()))

    def record_chat_rejected(reason: str) -> None:
        enqueue_analytics_event(
            event_name="chat_rejected",
            event_category="stream",
            user_id=user_id,
            session_id=thread_id,
            thread_id=thread_id,
            request_id=request_id,
            client_request_id=body.client_request_id,
            properties={
                "reason": reason,
                "complexity": body.complexity,
                "graph_mode": body.graph_mode,
                "research_enabled": body.research_enabled,
            },
        )

    thread = thread_store.get_thread(user_id, thread_id)
    if thread is None:
        record_chat_rejected("thread_not_found")
        return sse_error("Thread not found")

    # ── Pre-flight checks (synchronous, before opening the stream) ─────────────
    if byte_len(content) > settings.max_message_bytes:
        record_chat_rejected("message_too_large")
        return sse_error("Message too large (max 2KB)")

    if not content:
        record_chat_rejected("empty_message")
        return sse_error("Empty message")

    try:
        completed_turn = thread_store.get_completed_turn(
            user_id,
            thread_id,
            body.client_request_id,
        )
    except RuntimeError:
        logger.exception("Stored idempotent turn is incomplete")
        record_chat_rejected("incomplete_stored_turn")
        return sse_error("Previous request is incomplete — start a new request")
    if completed_turn is not None:
        enqueue_analytics_event(
            event_name="stream_replayed",
            event_category="stream",
            user_id=user_id,
            session_id=thread_id,
            thread_id=thread_id,
            request_id=request_id,
            client_request_id=body.client_request_id,
            properties={"stream_type": "chat"},
        )

        async def replay_completed_turn():
            yield sse(
                {
                    "type": "response_delta",
                    "content": completed_turn["assistant_content"],
                }
            )
            yield sse(
                {
                    "type": "graph_data",
                    "data": thread_store.get_graph(user_id, thread_id),
                }
            )
            yield sse({"type": "done"})

        return streaming_response(replay_completed_turn())

    message_count = message_store.count_messages(user_id, thread_id)
    if message_count + 2 > settings.max_messages_per_thread:
        record_chat_rejected("message_limit")
        return sse_error("Thread message limit reached. Start a new chat to continue.")

    limit_error = check_rate_limit(user_id)
    if limit_error:
        record_chat_rejected("rate_limited")
        return sse_error(limit_error)

    if not knowledge_base_ready(request):
        record_chat_rejected("knowledge_base_not_ready")
        return sse_error(
            "Knowledge base is still loading. Please try again in a moment."
        )

    if not check_prompt_injection(content):
        record_chat_rejected("security_filter")
        return sse_error("Message blocked by security filter")

    stream_id = runtime_state_store.try_acquire_active_stream(
        user_id,
        "chat",
        limit=settings.max_active_chat_streams_per_user,
        ttl_s=settings.agent_timeout_s + 30,
        scope_id=internal_test_stream_scope(user, thread_id),
    )
    if stream_id is None:
        record_chat_rejected("active_stream_limit")
        return sse_error(
            "Another response is already running. Stop it or wait for it to finish."
        )

    # ── Build tools bound to the loaded FAISS index ────────────────────────────
    rag_tools, graph_tools, node_detail_tools = _make_agent_tools(request)

    async def stream():
        from observability import (
            change_active_chat_streams,
            record_agent_duration,
            record_cancel,
            record_timeout,
        )

        # Queue bridges the agent (which calls send()) and the SSE generator (which yields).
        # run_agent is launched as a task; we drain the queue while it runs.
        queue: asyncio.Queue[dict] = asyncio.Queue(
            maxsize=max(1, settings.max_sse_queue_events),
        )
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        started_at = time.perf_counter()
        first_token_latency_ms: int | None = None
        response_delta_count = 0
        graph_event_count = 0
        history = message_store.get_history(
            user_id, thread_id, limit=settings.max_messages_per_thread
        )
        existing_graph = thread_store.get_graph(user_id, thread_id)

        enqueue_analytics_event(
            event_name="stream_started",
            event_category="stream",
            user_id=user_id,
            session_id=thread_id,
            thread_id=thread_id,
            request_id=request_id,
            client_request_id=body.client_request_id,
            properties={
                "stream_type": "chat",
                "complexity": body.complexity,
                "graph_mode": body.graph_mode,
                "research_enabled": body.research_enabled,
                "history_messages": len(history),
            },
        )

        async def send(event: dict) -> None:
            # Only the transport may publish the terminal event, after the
            # completed turn has been durably persisted.
            if event.get("type") == "done":
                return
            await queue.put(event)

        async def await_search_tool_request(request_id: str, timeout_s: float) -> bool:
            expires_at_epoch = time.time() + timeout_s
            runtime_state_store.prune_search_tool_requests(older_than_epoch=time.time())
            runtime_state_store.create_search_tool_request(
                request_id,
                user_id,
                thread_id,
                expires_at_epoch=expires_at_epoch,
            )
            try:
                deadline = asyncio.get_event_loop().time() + timeout_s
                while asyncio.get_event_loop().time() < deadline:
                    if runtime_state_store.is_search_tool_requested(
                        request_id, user_id, thread_id
                    ):
                        return True
                    await asyncio.sleep(0.1)
                return False
            finally:
                runtime_state_store.delete_search_tool_request(request_id)

        await send(
            {
                "type": "worker_status",
                "worker": "orchestrator",
                "status": "Question received — preparing context…",
            }
        )

        workflow_started_at = asyncio.get_running_loop().time()
        terminal_deadline = (
            workflow_started_at
            + settings.agent_timeout_s
            - settings.agent_terminal_headroom_s
        )

        state: AgentState = {
            "session_id": thread_id,
            "user_id": user_id,
            "user_email": user["email"] or f"{user_id}@unknown.local",
            "is_production": is_production_traffic(user),
            "request_id": request_id,
            "client_request_id": body.client_request_id,
            "user_message": content,
            "history": history,
            "complexity": body.complexity,
            "graph_mode": body.graph_mode,
            "research_enabled": body.research_enabled,
            "route": "",
            "rag_chunks": [],
            "retrieval_relevance": "strong",
            "retrieval_notice": "",
            "graph_data": existing_graph,
            "graph_changed": False,
            "graph_notice_sent": False,
            "research_context": "",
            "response_text": "",
            "send": send,
            "await_search_tool_request": await_search_tool_request,
            "workflow_started_at_s": workflow_started_at,
            "terminal_deadline_s": terminal_deadline,
            "graph_preview_deadline_s": (
                workflow_started_at + settings.graph_preview_timeout_s
            ),
        }

        agent_task = asyncio.create_task(
            run_agent(state, rag_tools, graph_tools, node_detail_tools)
        )
        change_active_chat_streams(1)

        try:
            # Drain queue until agent finishes AND queue is empty.
            # Short timeout on each get() so we re-check agent_task.done() frequently.
            # Hard wall-clock timeout aborts the task if it runs too long.
            while True:
                if asyncio.get_running_loop().time() >= terminal_deadline:
                    agent_task.cancel()
                    record_timeout()
                    enqueue_analytics_event(
                        event_name="stream_timeout",
                        event_category="stream",
                        user_id=user_id,
                        session_id=thread_id,
                        thread_id=thread_id,
                        request_id=request_id,
                        client_request_id=body.client_request_id,
                        numeric_value=max(
                            1, int((time.perf_counter() - started_at) * 1000)
                        ),
                        unit="ms",
                        properties={
                            "stream_type": "chat",
                            "first_token_latency_ms": first_token_latency_ms,
                            "response_delta_count": response_delta_count,
                            "graph_event_count": graph_event_count,
                        },
                    )
                    yield sse(
                        {
                            "type": "error",
                            "content": "Response timed out — please try again",
                        }
                    )
                    yield sse({"type": "done"})
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.05)
                    if event.get("type") == "response_delta":
                        response_delta_count += 1
                        if first_token_latency_ms is None:
                            first_token_latency_ms = max(
                                1, int((time.perf_counter() - started_at) * 1000)
                            )
                            enqueue_analytics_event(
                                event_name="stream_first_token",
                                event_category="stream",
                                user_id=user_id,
                                session_id=thread_id,
                                thread_id=thread_id,
                                request_id=request_id,
                                client_request_id=body.client_request_id,
                                numeric_value=first_token_latency_ms,
                                unit="ms",
                                properties={
                                    "stream_type": "chat",
                                    "latency_ms": first_token_latency_ms,
                                },
                            )
                    elif event.get("type") == "graph_data":
                        graph_event_count += 1
                    yield sse(event)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        agent_task.cancel()
                        record_cancel()
                        enqueue_analytics_event(
                            event_name="stream_cancelled",
                            event_category="stream",
                            user_id=user_id,
                            session_id=thread_id,
                            thread_id=thread_id,
                            request_id=request_id,
                            client_request_id=body.client_request_id,
                            numeric_value=max(
                                1, int((time.perf_counter() - started_at) * 1000)
                            ),
                            unit="ms",
                            properties={
                                "stream_type": "chat",
                                "first_token_latency_ms": first_token_latency_ms,
                                "response_delta_count": response_delta_count,
                                "graph_event_count": graph_event_count,
                            },
                        )
                        return
                    if agent_task.done() and queue.empty():
                        break
        except asyncio.CancelledError:
            agent_task.cancel()
            record_cancel()
            raise
        finally:
            change_active_chat_streams(-1)
            runtime_state_store.release_active_stream(stream_id)
            if not agent_task.done():
                agent_task.cancel()
                with suppress(asyncio.CancelledError):
                    await agent_task
            record_agent_duration(
                max(1, int((time.perf_counter() - started_at) * 1000)),
                route="/api/chat",
            )

        # Surface any unhandled agent exception as an SSE error event
        if not agent_task.cancelled():
            exc = agent_task.exception()
            if exc:
                enqueue_analytics_event(
                    event_name="stream_failed",
                    event_category="stream",
                    user_id=user_id,
                    session_id=thread_id,
                    thread_id=thread_id,
                    request_id=request_id,
                    client_request_id=body.client_request_id,
                    numeric_value=max(
                        1, int((time.perf_counter() - started_at) * 1000)
                    ),
                    unit="ms",
                    properties={
                        "stream_type": "chat",
                        "error_type": type(exc).__name__,
                        "first_token_latency_ms": first_token_latency_ms,
                        "response_delta_count": response_delta_count,
                        "graph_event_count": graph_event_count,
                    },
                )
                logger.error("Agent stream failed: %s", type(exc).__name__)
                yield sse(
                    {"type": "error", "content": "Response failed — please try again"}
                )
                return

            final_state = agent_task.result()
            output_shape = output_shape_from_final_state(final_state)
            try:
                title = thread["title"]
                if title == "New chat":
                    title = truncate_utf8(
                        content, min(60, settings.max_thread_title_bytes)
                    )
                graph_saved = thread_store.persist_turn(
                    user_id,
                    thread_id,
                    title=title,
                    user_content=content,
                    assistant_content=final_state["response_text"],
                    graph_data=final_state.get("graph_data"),
                    client_request_id=body.client_request_id,
                )
                if not graph_saved:
                    yield sse(
                        {
                            "type": "error",
                            "content": (
                                "Graph is large — it's displayed above but won't be saved. "
                                "Start a new chat to reset."
                            ),
                        }
                    )
            except ThreadMessageLimitExceeded:
                yield sse(
                    {
                        "type": "error",
                        "content": "Thread message limit reached. Start a new chat to continue.",
                    }
                )
                return
            except Exception:
                logger.exception("Chat result persistence failed")
                enqueue_analytics_event(
                    event_name="stream_failed",
                    event_category="stream",
                    user_id=user_id,
                    session_id=thread_id,
                    thread_id=thread_id,
                    request_id=request_id,
                    client_request_id=body.client_request_id,
                    properties={
                        "stream_type": "chat",
                        "error_type": "PersistenceError",
                        "first_token_latency_ms": first_token_latency_ms,
                        "response_delta_count": response_delta_count,
                        "graph_event_count": graph_event_count,
                        **output_shape,
                    },
                )
                yield sse(
                    {
                        "type": "error",
                        "content": "Response could not be saved — please try again",
                    }
                )
                return

            duration_ms = max(1, int((time.perf_counter() - started_at) * 1000))
            enqueue_analytics_event(
                event_name="stream_completed",
                event_category="stream",
                user_id=user_id,
                session_id=thread_id,
                thread_id=thread_id,
                request_id=request_id,
                client_request_id=body.client_request_id,
                numeric_value=duration_ms,
                unit="ms",
                properties={
                    "stream_type": "chat",
                    "duration_ms": duration_ms,
                    "first_token_latency_ms": first_token_latency_ms,
                    "response_delta_count": response_delta_count,
                    "graph_event_count": graph_event_count,
                    **output_shape,
                },
            )
            enqueue_analytics_event(
                event_name="retrieval_quality",
                event_category="quality_score",
                user_id=user_id,
                session_id=thread_id,
                thread_id=thread_id,
                request_id=request_id,
                client_request_id=body.client_request_id,
                numeric_value=1.0
                if final_state.get("retrieval_relevance") == "strong"
                else 0.3,
                unit="score",
                properties={
                    "score_name": "retrieval_relevance",
                    "score_max": 1.0,
                    "retrieval_relevance": final_state.get("retrieval_relevance"),
                    "retrieval_chunk_count": output_shape["retrieval_chunk_count"],
                    "route": final_state.get("route"),
                },
            )

            yield sse(
                {
                    "type": "graph_data",
                    "data": thread_store.get_graph(user_id, thread_id),
                }
            )
            yield sse({"type": "done"})

    return streaming_response(stream())


@router.post("/chat/use-search-tool")
async def use_search_tool_endpoint(
    body: SearchToolRequest, user=Depends(get_current_user)
):
    user_id = user["id"]
    thread = thread_store.get_thread(user_id, body.thread_id)
    if thread is None:
        return {"ok": False, "status": "thread_not_found"}

    runtime_state_store.prune_search_tool_requests(older_than_epoch=time.time())
    requested = runtime_state_store.mark_search_tool_requested(
        body.request_id, user_id, body.thread_id
    )
    if not requested:
        return {"ok": False, "status": "expired"}

    return {"ok": True, "status": "search_requested"}


@router.post("/node-selected")
async def node_selected_endpoint(
    body: NodeSelectedRequest, request: Request, user=Depends(get_current_user)
):
    """
    Generate 3 suggested follow-up questions for a clicked graph node.
    Streams a single suggested_questions event then a done event.
    """
    user_id = user["id"]
    upsert_profile(user_id, user["email"] or f"{user_id}@unknown.local")
    thread_id = body.thread_id
    request.state.thread_id = thread_id
    request.state.client_request_id = body.client_request_id
    node_title = body.title
    node_description = body.description
    thread = thread_store.get_thread(user_id, thread_id)
    if thread is None:
        return sse_error("Thread not found", include_done=True)

    if not body.node_id:
        return sse_error("Missing node id", include_done=True)

    if not node_title:
        return sse_error("Missing node title", include_done=True)

    if byte_len(f"{node_title}\n{node_description}") > settings.max_node_text_bytes:
        return sse_error("Selected node payload too large", include_done=True)

    limit_error = check_rate_limit(user_id)
    if limit_error:
        return sse_error(limit_error, include_done=True)

    stream_id = runtime_state_store.try_acquire_active_stream(
        user_id,
        "node-selected",
        limit=settings.max_active_node_streams_per_user,
        ttl_s=45,
    )
    if stream_id is None:
        return sse_error(
            "Too many node detail requests are already running", include_done=True
        )

    history = message_store.get_history(user_id, thread_id, limit=6)

    async def stream():
        try:
            async for event in stream_suggested_questions(
                node_title,
                node_description,
                history,
                telemetry={
                    "operation": "node_selected_chips",
                    "user_id": user_id,
                    "thread_id": thread_id,
                    "metadata": {"node_id": body.node_id},
                },
            ):
                yield sse(event)
        finally:
            runtime_state_store.release_active_stream(stream_id)

    return streaming_response(stream())
