"""
Конфигурационный файл для микросервиса OpenAI.
"""
import os

# OpenAI API
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "sk-proj-Qf3a4WNYCh53xQwV7ANDk3ogN7vwmZYfRbnBnpDIEPTT94Wg47cY-fT3aR4v8G-ZLbQkA")
OPENAI_ORG_ID = os.environ.get("OPENAI_ORG_ID", "org-ku3Bs24jFSwBDFddBt8Z1pQ9")  # ← NEW

# API безопасность
API_TOKEN = os.environ.get("API_TOKEN", "7supersecrettoken77")  # заголовок X-API-Key, которым подписываются все запросы

# Хранилище данных
DATA_DIR = os.environ.get("DATA_DIR", "data")
THREADS_FILENAME = os.environ.get("THREADS_FILENAME", "threads.json")

# Настройки автоматического сброса трейдов
INACTIVE_HOURS = int(os.environ.get("INACTIVE_HOURS", "5"))  # Часы неактивности для сброса трейдов
CLEANUP_INTERVAL = int(os.environ.get("CLEANUP_INTERVAL", "10"))  # Интервал проверки в минутах
SAVE_INTERVAL = int(os.environ.get("SAVE_INTERVAL", "5"))  # Интервал сохранения в минутах

# Настройки сервера
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))

