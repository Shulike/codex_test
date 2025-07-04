"""
Модуль безопасности для микросервиса OpenAI.
Обеспечивает защиту API с помощью токена.
"""
import logging
from fastapi import Security, HTTPException, Depends
from fastapi.security.api_key import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN

import config

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header is None:
        logger.warning("Отсутствует заголовок X-API-Key")
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Отсутствует заголовок X-API-Key")
    if api_key_header != config.API_TOKEN:
        logger.warning(f"Невалидный API-ключ: {api_key_header}")
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Невалидный API-ключ")
    return api_key_header

