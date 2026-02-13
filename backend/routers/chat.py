import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from backend.database import get_db
from backend.models.user import User
from backend.models.account import GoogleAccount
from backend.models.chat import ChatConversation, ChatMessage
from backend.routers.auth import get_current_user
from backend.services.chat import ChatService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

chat_service = ChatService()


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[int] = None


class ConversationSummary(BaseModel):
    id: int
    title: Optional[str] = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    id: int
    role: str
    content: Optional[str] = None
    plan: Optional[dict] = None
    task_results: Optional[dict] = None
    tokens_used: Optional[int] = None
    created_at: str

    model_config = {"from_attributes": True}


class ConversationDetail(BaseModel):
    id: int
    title: Optional[str] = None
    created_at: str
    updated_at: str
    messages: list[MessageResponse]


# ---------------------------------------------------------------------------
# SSE streaming chat endpoint
# ---------------------------------------------------------------------------

@router.post("")
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start or continue a chat conversation. Returns SSE stream."""
    # Get user's account IDs and descriptions
    acct_result = await db.execute(
        select(GoogleAccount.id, GoogleAccount.email, GoogleAccount.description)
        .where(GoogleAccount.user_id == user.id)
    )
    acct_rows = acct_result.all()
    account_ids = [r[0] for r in acct_rows]
    account_contexts = [
        {"email": r[1], "description": r[2]}
        for r in acct_rows
    ]

    if not account_ids:
        raise HTTPException(
            status_code=400,
            detail="No email accounts connected. Connect a Google account first.",
        )

    # Get or create conversation
    conversation = None
    if body.conversation_id:
        result = await db.execute(
            select(ChatConversation).where(
                ChatConversation.id == body.conversation_id,
                ChatConversation.user_id == user.id,
            )
        )
        conversation = result.scalar_one_or_none()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    
    if not conversation:
        title = body.message[:80].strip()
        if len(body.message) > 80:
            title += "..."
        conversation = ChatConversation(
            user_id=user.id,
            title=title,
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)

    # Save user message
    user_msg = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content=body.message,
    )
    db.add(user_msg)
    await db.commit()

    conv_id = conversation.id
    user_id = user.id

    async def generate():
        """Generator that runs the agent and yields SSE events."""
        from backend.database import async_session

        async with async_session() as stream_db:
            # Reload user for preferences
            user_result = await stream_db.execute(
                select(User).where(User.id == user_id)
            )
            stream_user = user_result.scalar_one()

            # Load conversation history for follow-up context
            conversation_history = []
            if body.conversation_id:
                from sqlalchemy.orm import selectinload
                conv_result = await stream_db.execute(
                    select(ChatConversation)
                    .options(selectinload(ChatConversation.messages))
                    .where(ChatConversation.id == conv_id)
                )
                conv_obj = conv_result.scalar_one_or_none()
                if conv_obj and conv_obj.messages:
                    # Include prior messages but not the current one we just saved
                    for m in conv_obj.messages:
                        if m.content and m.content != body.message:
                            conversation_history.append({
                                "role": m.role,
                                "content": m.content,
                            })

            final_content = ""
            plan_data = None
            task_results = {}
            total_tokens = 0
            is_clarification = False

            try:
                async for sse_event in chat_service.run_chat(
                    user_query=body.message,
                    user=stream_user,
                    account_ids=account_ids,
                    db=stream_db,
                    conversation_history=conversation_history if conversation_history else None,
                    account_contexts=account_contexts,
                ):
                    # Parse the event to capture data for storage
                    try:
                        # Extract the data portion from the SSE string
                        lines = sse_event.strip().split("\n")
                        event_type = ""
                        event_data = ""
                        for line in lines:
                            if line.startswith("event: "):
                                event_type = line[7:]
                            elif line.startswith("data: "):
                                event_data = line[6:]

                        if event_data:
                            parsed = json.loads(event_data)
                            if event_type == "plan_ready":
                                plan_data = parsed.get("tasks")
                            elif event_type == "task_complete":
                                task_results[parsed.get("task_id")] = parsed.get("summary", "")
                            elif event_type == "task_failed":
                                task_results[parsed.get("task_id")] = f"Failed: {parsed.get('error', '')}"
                            elif event_type == "content":
                                final_content = parsed.get("text", "")
                            elif event_type == "clarification":
                                final_content = parsed.get("question", "")
                                is_clarification = True
                            elif event_type == "done":
                                total_tokens = parsed.get("tokens_used", 0)
                    except (json.JSONDecodeError, Exception):
                        pass

                    yield sse_event

            except Exception as e:
                logger.error(f"Chat stream error: {e}")
                yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

            # Save assistant message with results
            try:
                assistant_msg = ChatMessage(
                    conversation_id=conv_id,
                    role="assistant",
                    content=final_content,
                    plan={"tasks": plan_data} if plan_data else None,
                    task_results=task_results if task_results else None,
                    tokens_used=total_tokens,
                )
                stream_db.add(assistant_msg)
                await stream_db.commit()

                # Yield the conversation_id in the done event
                yield f"event: conversation_id\ndata: {json.dumps({'conversation_id': conv_id})}\n\n"
            except Exception as e:
                logger.error(f"Failed to save assistant message: {e}")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Conversation CRUD
# ---------------------------------------------------------------------------

@router.get("/conversations")
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all conversations for the current user."""
    result = await db.execute(
        select(ChatConversation)
        .where(ChatConversation.user_id == user.id)
        .order_by(desc(ChatConversation.updated_at))
    )
    conversations = result.scalars().all()

    return [
        {
            "id": c.id,
            "title": c.title,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in conversations
    ]


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a conversation with all its messages."""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(ChatConversation)
        .options(selectinload(ChatConversation.messages))
        .where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = []
    for m in conversation.messages:
        messages.append({
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "plan": m.plan,
            "task_results": m.task_results,
            "tokens_used": m.tokens_used,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })

    return {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
        "messages": messages,
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a conversation."""
    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await db.delete(conversation)
    await db.commit()
    return {"message": "Conversation deleted"}
