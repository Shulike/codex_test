"""
Сервис для работы с OpenAI API.
"""
import logging
from typing import Dict, Any, Optional, List
import openai
import config

from openai import NotFoundError, APIError

logger = logging.getLogger(__name__)

class OpenAIService:
    """Класс для работы с OpenAI API."""
    def __init__(self):
        self.client = openai.AsyncOpenAI(
            api_key=config.OPENAI_API_KEY,
            organization=(config.OPENAI_ORG_ID or None),
        )
    async def create_thread(self, initial_message: str = None) -> Any:
        try:
            thread = await self.client.beta.threads.create()
            if initial_message:
                await self.add_message(thread.id, "user", initial_message)
            return thread
        except Exception as e:
            logger.error(f"Ошибка при создании треда: {e}")
            raise
    async def add_message(self, thread_id: str, role: str, content: str) -> Any:
        try:
            message = await self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role=role,
                content=content
            )
            return message
        except Exception as e:
            logger.error(f"Ошибка при добавлении сообщения в тред {thread_id}: {e}")
            raise
    async def create_run(self, thread_id: str, assistant_id: str) -> Any:
        try:
            run = await self.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=assistant_id
            )
            return run
        except Exception as e:
            logger.error(f"Ошибка при создании запуска для треда {thread_id}: {e}")
            raise
    async def get_run(self, thread_id: str, run_id: str) -> Any:
        try:
            run = await self.client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run_id
            )
            return run
        except Exception as e:
            logger.error(f"Ошибка при получении информации о запуске {run_id} для треда {thread_id}: {e}")
            raise
    async def cancel_run(self, thread_id: str, run_id: str) -> Any:
        try:
            run = await self.client.beta.threads.runs.cancel(
                thread_id=thread_id,
                run_id=run_id
            )
            return run
        except Exception as e:
            logger.error(f"Ошибка при отмене запуска {run_id} для треда {thread_id}: {e}")
            raise
    async def get_messages(self, thread_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            messages = await self.client.beta.threads.messages.list(
                thread_id=thread_id,
                limit=limit
            )
            result = []
            for message in messages.data:
                if message.content and len(message.content) > 0:
                    text_obj = message.content[0].text
                    content = text_obj.value
                    annotations_list = []
                    if hasattr(text_obj, "annotations") and text_obj.annotations:
                        for ann in text_obj.annotations:
                            file_citation = getattr(ann, "file_citation", None)
                            if file_citation:
                                annotation_dict = {
                                    "text": ann.text,
                                    "file_citation": {
                                        "file_id": file_citation.file_id
                                    }
                                }
                            else:
                                annotation_dict = {
                                    "text": ann.text,
                                    "file_citation": None
                                }
                            annotations_list.append(annotation_dict)
                    else:
                        annotations_list = []
                else:
                    content = ""
                    annotations_list = []
                result.append({
                    "role": message.role,
                    "content": content,
                    "annotations": annotations_list
                })
            return result
        except Exception as e:
            logger.error(f"Ошибка при получении сообщений из треда {thread_id}: {e}")
            raise
    async def get_latest_message(self, thread_id: str) -> Optional[Dict[str, Any]]:
        try:
            messages = await self.get_messages(thread_id, limit=1)
            return messages[0] if messages else None
        except Exception as e:
            logger.error(f"Ошибка при получении последнего сообщения из треда {thread_id}: {e}")
            return None
    async def retrieve_file(self, file_id: str) -> Optional[Dict[str, str]]:
        try:
            file_obj = await self.client.files.retrieve(file_id)
            return {"filename": file_obj.filename}
        except OpenAIError as e:
            logger.warning("OpenAI file not found (%s): %s", file_id, e)
            return None
        except Exception as ex:
            logger.error(f"Ошибка при retrieve_file({file_id}): {ex}")
            return None
