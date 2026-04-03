from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from adapters.supabase_auth_adapter import get_current_user
from storage.message_store import get_messages
from storage.profile_store import upsert_profile
from storage.thread_store import create_thread, delete_thread, get_latest_thread, get_thread, list_threads

router = APIRouter(prefix="/api/threads", tags=["threads"])


class CreateThreadRequest(BaseModel):
    title: str = "New chat"


@router.get("")
async def list_threads_endpoint(user=Depends(get_current_user)):
    upsert_profile(user["id"], user["email"] or f"{user['id']}@unknown.local")
    return {"threads": list_threads(user["id"])}


@router.post("")
async def create_thread_endpoint(body: CreateThreadRequest, user=Depends(get_current_user)):
    upsert_profile(user["id"], user["email"] or f"{user['id']}@unknown.local")
    thread = create_thread(user["id"], body.title.strip() or "New chat")
    return {"thread": thread, "messages": []}


@router.get("/latest")
async def latest_thread_endpoint(user=Depends(get_current_user)):
    upsert_profile(user["id"], user["email"] or f"{user['id']}@unknown.local")
    thread = get_latest_thread(user["id"])
    if thread is None:
        thread = create_thread(user["id"])
    return {
        "thread": thread,
        "messages": get_messages(user["id"], thread["id"]),
    }


@router.delete("/{thread_id}", status_code=204)
async def delete_thread_endpoint(thread_id: str, user=Depends(get_current_user)):
    thread = get_thread(user["id"], thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    delete_thread(user["id"], thread_id)


@router.get("/{thread_id}")
async def get_thread_endpoint(thread_id: str, user=Depends(get_current_user)):
    upsert_profile(user["id"], user["email"] or f"{user['id']}@unknown.local")
    thread = get_thread(user["id"], thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {
        "thread": thread,
        "messages": get_messages(user["id"], thread_id),
    }
