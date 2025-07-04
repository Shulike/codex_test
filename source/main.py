"""
Основной файл микросервиса OpenAI без БД.
"""
import os
import asyncio
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from starlette.status import HTTP_403_FORBIDDEN

import config
from routers import threads
from routers import file_meta  # <-- NEW: импортируем новый роутер
from storage.file_storage import FileStorage
from storage.thread_manager import ThreadManager
from services.openai_svc import OpenAIService
from services.scheduler import Scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="OpenAI Microservice",
    description="Микросервис для работы с OpenAI API без использования БД",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if request.url.path in ["/docs", "/redoc", "/openapi.json", "/"]:
        return await call_next(request)
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        return HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Отсутствует заголовок X-API-Key").__call__(request)
    if api_key != config.API_TOKEN:
        return HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Невалидный API-ключ").__call__(request)
    return await call_next(request)

file_storage = FileStorage()
openai_service = OpenAIService()
thread_manager = ThreadManager(storage=file_storage, openai_service=openai_service)

scheduler = Scheduler(thread_manager)

app.include_router(threads.router)
app.include_router(file_meta.router)

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html(request: Request):
    api_key = request.headers.get("X-API-Key")
    if api_key != config.API_TOKEN:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Невалидный API-ключ для доступа к документации")
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=app.title + " - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
    )

@app.get("/openapi.json", include_in_schema=False)
async def get_open_api_endpoint(request: Request):
    api_key = request.headers.get("X-API-Key")
    if api_key != config.API_TOKEN:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Невалидный API-ключ для доступа к OpenAPI схеме")
    return get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

@app.on_event("startup")
async def startup_event():
    logger.info("Запуск микросервиса OpenAI без БД")
    os.makedirs(config.DATA_DIR, exist_ok=True)
    logger.info("Данные загружены при инициализации FileStorage")
    asyncio.create_task(scheduler.start())

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Остановка микросервиса OpenAI")
    await scheduler.stop()
    file_storage.periodic_save()

@app.get("/")
async def root():
    return {"message": "OpenAI Microservice API", "version": app.version}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=True
    )

