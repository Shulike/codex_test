"""
Схемы данных для микросервиса OpenAI.
"""
from pydantic import BaseModel
from typing import Optional, List

class CreateThreadRequest(BaseModel):
    initial_message: str

class CreateThreadResponse(BaseModel):
    thread_id: str

class AddMessageRequest(BaseModel):
    thread_id: str
    role: str
    content: str

class RunRequest(BaseModel):
    thread_id: str
    assistant_id: str

class RunResponse(BaseModel):
    run_id: str

class CancelRunRequest(BaseModel):
    thread_id: str

class ThreadStatusResponse(BaseModel):
    status: str
    detail: Optional[str] = None

class MessageListResponse(BaseModel):
    messages: List[dict]

