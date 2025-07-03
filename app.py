import os
import time
import sqlite3
from datetime import datetime, timedelta
import logging
from typing import Optional, List

import requests
from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response
from starlette.status import HTTP_302_FOUND
from jinja2 import pass_context
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET_KEY", "change-me"))

logging.basicConfig(level=logging.INFO)

openai_api_key = os.environ.get('OPENAI_API_KEY')
if not openai_api_key:
    raise RuntimeError('OPENAI_API_KEY environment variable not set')

client = OpenAI(api_key=openai_api_key, default_headers={"OpenAI-Beta": "assistants=v2"})

DB_PATH = os.environ.get("DB_PATH", "app.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        if not db.execute("SELECT 1 FROM settings WHERE key='registration_open'").fetchone():
            db.execute("INSERT INTO settings (key, value) VALUES ('registration_open','1')")

init_db()

def get_setting(key: str, default: Optional[str] = None):
    with get_db() as db:
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default

def set_setting(key: str, value: str):
    with get_db() as db:
        if db.execute('SELECT 1 FROM settings WHERE key=?', (key,)).fetchone():
            db.execute('UPDATE settings SET value=? WHERE key=?', (value, key))
        else:
            db.execute('INSERT INTO settings (key, value) VALUES (?, ?)', (key, value))

# flash helpers
@pass_context
def get_flashed_messages(ctx):
    request: Request = ctx['request']
    msgs = request.session.pop('_messages', [])
    return msgs

def flash(request: Request, message: str):
    request.session.setdefault('_messages', []).append(message)

def flash_error(request: Request, message: str):
    logging.error(message)
    flash(request, message)

@pass_context
def url_for(ctx, name: str, **path_params):
    request: Request = ctx['request']
    return request.url_for(name, **path_params)

templates = Jinja2Templates(directory='templates')
templates.env.globals['get_flashed_messages'] = get_flashed_messages
templates.env.globals['url_for'] = url_for

@pass_context
def current_user_ctx(ctx):
    request: Request = ctx['request']
    return current_user(request)

templates.env.globals['current_user'] = current_user_ctx

def current_user(request: Request):
    uid = request.session.get('user_id')
    if not uid:
        return None
    with get_db() as db:
        return db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()

def login_required(request: Request):
    if not request.session.get('user_id'):
        raise HTTPException(status_code=401)

def list_gpt_models() -> List[str]:
    try:
        models = client.models.list().data
        return sorted({m.id for m in models if m.id.startswith('gpt-')})
    except Exception as e:
        logging.error("failed to list models: %s", e)
        return ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"]

@app.get('/register', response_class=HTMLResponse)
async def register_form(request: Request):
    if get_setting('registration_open','1') != '1':
        flash(request, 'Регистрация закрыта администратором')
        return RedirectResponse(url=request.url_for('login_form'), status_code=HTTP_302_FOUND)
    return templates.TemplateResponse('register.html', {'request': request, 'title':'Регистрация'})

@app.post('/register')
async def register(request: Request, username: str = Form(...), password: str = Form(...)):
    if get_setting('registration_open','1') != '1':
        flash(request, 'Регистрация закрыта администратором')
        return RedirectResponse(url=request.url_for('login_form'), status_code=HTTP_302_FOUND)
    with get_db() as db:
        try:
            db.execute('INSERT INTO users (username, password) VALUES (?,?)', (username, generate_password_hash(password)))
            flash(request, 'Регистрация успешна')
            return RedirectResponse(url=request.url_for('login_form'), status_code=HTTP_302_FOUND)
        except sqlite3.IntegrityError:
            flash(request, 'Пользователь уже существует')
            return RedirectResponse(url=request.url_for('register_form'), status_code=HTTP_302_FOUND)

@app.get('/login', response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse('login.html', {'request': request, 'title':'Вход'})

@app.post('/login')
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with get_db() as db:
        user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
    if not user or not check_password_hash(user['password'], password):
        flash(request, 'Неверные учетные данные')
        return RedirectResponse(url=request.url_for('login_form'), status_code=HTTP_302_FOUND)
    request.session['user_id'] = user['id']
    next_url = request.query_params.get('next') or request.url_for('index')
    return RedirectResponse(url=next_url, status_code=HTTP_302_FOUND)

@app.post('/logout')
async def logout(request: Request):
    request.session.pop('user_id', None)
    return RedirectResponse(url=request.url_for('login_form'), status_code=HTTP_302_FOUND)

@app.get('/settings', response_class=HTMLResponse)
async def settings_form(request: Request):
    login_required(request)
    return templates.TemplateResponse('settings.html', {
        'request': request,
        'title': 'Настройка сайта',
        'registration_open': get_setting('registration_open','1') == '1'
    })

@app.post('/settings')
async def settings_update(request: Request,
    current_password: str = Form(None), new_password: str = Form(None),
    change_password: str = Form(None), registration_open: str = Form('off'),
    update_registration: str = Form(None)):
    login_required(request)
    if change_password:
        if not current_password or not new_password:
            flash_error(request, 'Введите текущий и новый пароль')
            return RedirectResponse(request.url_for('settings_form'), status_code=HTTP_302_FOUND)
        with get_db() as db:
            user = db.execute('SELECT * FROM users WHERE id=?', (request.session['user_id'],)).fetchone()
            if not user or not check_password_hash(user['password'], current_password):
                flash_error(request, 'Неверный текущий пароль')
            else:
                db.execute('UPDATE users SET password=? WHERE id=?', (generate_password_hash(new_password), user['id']))
                flash(request, 'Пароль обновлён')
    if update_registration:
        set_setting('registration_open', '1' if registration_open == 'on' else '0')
        flash(request, 'Настройки сохранены')
    return RedirectResponse(request.url_for('settings_form'), status_code=HTTP_302_FOUND)

def get_billing_data():
    headers = {'Authorization': f'Bearer {openai_api_key}'}
    try:
        sub = requests.get('https://api.openai.com/dashboard/billing/subscription', headers=headers, timeout=10).json()
        if 'error' in sub:
            raise RuntimeError(sub['error'].get('message','billing error'))
        credit = requests.get('https://api.openai.com/dashboard/billing/credit_grants', headers=headers, timeout=10).json()
        if 'error' in credit:
            raise RuntimeError(credit['error'].get('message','billing error'))
        end = datetime.utcnow().date()
        start = end - timedelta(days=30)
        usage = requests.get('https://api.openai.com/dashboard/billing/usage', params={'start_date': start.isoformat(), 'end_date': end.isoformat()}, headers=headers, timeout=10).json()
        if 'error' in usage:
            raise RuntimeError(usage['error'].get('message','billing error'))
        daily = []
        for day in usage.get('daily_costs', []):
            cost = sum(li.get('cost',0) for li in day.get('line_items',[]))
            daily.append({'date': day.get('timestamp','')[:10], 'cost': cost})
        total_usage = usage.get('total_usage',0)/100.0
        hard_limit = sub.get('hard_limit_usd',0.0)
        available = credit.get('total_available',0.0)
        if available == 0.0 and hard_limit:
            available = max(hard_limit - total_usage, 0.0)
        return {'daily': daily, 'total_usage': total_usage, 'available': available}
    except Exception as e:
        return {'daily': [], 'total_usage': 0.0, 'available': 0.0, 'error': str(e)}

@app.get('/', response_class=HTMLResponse)
async def index(request: Request):
    if not request.session.get('user_id'):
        return templates.TemplateResponse('landing.html', {'request':request, 'title':'OpenAi hub api v2.0'})
    billing = get_billing_data()
    if billing.get('error'):
        flash(request, f"Ошибка получения данных: {billing['error']}")
    return templates.TemplateResponse('index.html', {
        'request': request,
        'title': 'Дашборд',
        'daily': billing['daily'],
        'total_usage': billing['total_usage'],
        'available': billing['available'],
    })


# --------------- Assistants management ---------------

PAGE_SIZE = 10

@app.get('/assistants', response_class=HTMLResponse)
async def list_assistants(request: Request, page: int = 1, q: str = ''):
    login_required(request)
    try:
        assistants = client.beta.assistants.list(limit=100).data
    except Exception as e:
        flash_error(request, f'Ошибка: {e}')
        assistants = []
    if q:
        assistants = [a for a in assistants if q.lower() in (a.name or '').lower()]
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    prev_page = page - 1 if start > 0 else None
    next_page = page + 1 if end < len(assistants) else None
    return templates.TemplateResponse('assistants.html', {
        'request': request,
        'title': 'Ассистенты',
        'assistants': assistants[start:end],
        'prev_page': prev_page,
        'next_page': next_page,
        'q': q,
    })

@app.get('/assistants/new', response_class=HTMLResponse)
async def new_assistant_form(request: Request):
    login_required(request)
    models = list_gpt_models()
    try:
        vector_stores = client.vector_stores.list(limit=100).data
    except Exception:
        vector_stores = []
    return templates.TemplateResponse('new_assistant.html', {
        'request': request,
        'title': 'Создать ассистента',
        'models': models,
        'vector_stores': vector_stores,
        'default_model': 'gpt-4o-mini'
    })

@app.post('/assistants/new')
async def new_assistant(request: Request, name: str = Form(...), instructions: str = Form(''),
                        model: str = Form('gpt-4o-mini'), temperature: float = Form(0.30),
                        top_p: float = Form(0.15), vector_store_id: str = Form('')):
    login_required(request)
    params = {
        'name': name,
        'instructions': instructions,
        'model': model,
        'temperature': temperature,
        'top_p': top_p,
    }
    tool_resources = {}
    if vector_store_id:
        tool_resources['file_search'] = {'vector_store_ids': [vector_store_id]}
    if tool_resources:
        params['tool_resources'] = tool_resources
    try:
        client.beta.assistants.create(**params)
        flash(request, 'Ассистент создан')
    except Exception as e:
        flash_error(request, f'Ошибка: {e}')
    return RedirectResponse(request.url_for('list_assistants'), status_code=HTTP_302_FOUND)


@app.post('/assistants/{assistant_id}/delete')
async def delete_assistant(request: Request, assistant_id: str):
    login_required(request)
    try:
        client.beta.assistants.delete(assistant_id)
        flash(request, 'Ассистент удален')
    except Exception as e:
        flash_error(request, f'Ошибка: {e}')
    return RedirectResponse(request.url_for('list_assistants'), status_code=HTTP_302_FOUND)

@app.get('/assistants/{assistant_id}/test', response_class=HTMLResponse)
async def test_assistant(request: Request, assistant_id: str):
    login_required(request)
    try:
        assistant = client.beta.assistants.retrieve(assistant_id)
    except Exception as e:
        flash_error(request, f'Ошибка: {e}')
        return RedirectResponse(request.url_for('list_assistants'), status_code=HTTP_302_FOUND)
    threads = request.session.setdefault('threads', {})
    thread_id = threads.get(assistant_id)
    if not thread_id:
        thread = client.beta.threads.create()
        thread_id = thread.id
        threads[assistant_id] = thread_id
    try:
        messages = client.beta.threads.messages.list(thread_id, order='asc').data
    except Exception:
        messages = []
    return templates.TemplateResponse('test_assistant.html', {
        'request': request,
        'title': 'Тестирование',
        'assistant': assistant,
        'messages': messages,
    })

@app.post('/assistants/{assistant_id}/test')
async def send_assistant_message(request: Request, assistant_id: str, prompt: str = Form('')):
    login_required(request)
    threads = request.session.setdefault('threads', {})
    thread_id = threads.get(assistant_id)
    if not thread_id:
        thread = client.beta.threads.create()
        thread_id = thread.id
        threads[assistant_id] = thread_id
    if prompt:
        try:
            client.beta.threads.messages.create(thread_id, role='user', content=prompt)
            run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=assistant_id)
            while run.status in ('queued','in_progress'):
                time.sleep(1)
                run = client.beta.threads.runs.retrieve(run.id, thread_id=thread_id)
        except Exception as e:
            flash_error(request, f'Ошибка: {e}')
    return RedirectResponse(request.url_for('test_assistant', assistant_id=assistant_id), status_code=HTTP_302_FOUND)

@app.post('/assistants/{assistant_id}/reset')
async def reset_assistant_thread(request: Request, assistant_id: str):
    login_required(request)
    threads = request.session.setdefault('threads', {})
    thread_id = threads.pop(assistant_id, None)
    if thread_id:
        try:
            client.beta.threads.delete(thread_id)
        except Exception:
            pass
    return RedirectResponse(request.url_for('test_assistant', assistant_id=assistant_id), status_code=HTTP_302_FOUND)

# --------------- Vector store (File Search) management ---------------

@app.get('/filesearch', response_class=HTMLResponse)
async def list_vector_stores(request: Request, page: int = 1, q: str = ''):
    login_required(request)
    try:
        stores = client.vector_stores.list(limit=100).data
    except Exception as e:
        flash_error(request, f'Ошибка: {e}')
        stores = []
    if q:
        stores = [v for v in stores if q.lower() in (v.name or '').lower()]
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    prev_page = page - 1 if start > 0 else None
    next_page = page + 1 if end < len(stores) else None
    return templates.TemplateResponse('vector_stores.html', {
        'request': request,
        'title': 'File Search',
        'vector_stores': stores[start:end],
        'prev_page': prev_page,
        'next_page': next_page,
        'q': q,
    })

@app.get('/filesearch/new', response_class=HTMLResponse)
async def new_vector_store_form(request: Request):
    login_required(request)
    return templates.TemplateResponse('new_vector_store.html', {
        'request': request,
        'title': 'Создать File Search'
    })

@app.post('/filesearch/new')
async def new_vector_store(request: Request, name: str = Form(...), file_id: str = Form('')):
    login_required(request)
    params = {'name': name}
    if file_id:
        params['file_ids'] = [file_id]
    try:
        client.vector_stores.create(**params)
        flash(request, 'File Search создан')
    except Exception as e:
        flash_error(request, f'Ошибка: {e}')
    return RedirectResponse(request.url_for('list_vector_stores'), status_code=HTTP_302_FOUND)

@app.get('/filesearch/{store_id}', response_class=HTMLResponse)
async def view_vector_store(request: Request, store_id: str):
    login_required(request)
    try:
        store = client.vector_stores.retrieve(store_id)
        files = client.vector_stores.files.list(store_id, limit=100).data
    except Exception as e:
        flash_error(request, f'Ошибка: {e}')
        return RedirectResponse(request.url_for('list_vector_stores'), status_code=HTTP_302_FOUND)
    return templates.TemplateResponse('view_vector_store.html', {
        'request': request,
        'title': 'Файлы',
        'vector_store': store,
        'files': files,
    })

@app.post('/filesearch/{store_id}/delete')
async def delete_vector_store(request: Request, store_id: str):
    login_required(request)
    try:
        client.vector_stores.delete(store_id)
        flash(request, 'File Search удалён')
    except Exception as e:
        flash_error(request, f'Ошибка: {e}')
    return RedirectResponse(request.url_for('list_vector_stores'), status_code=HTTP_302_FOUND)

@app.post('/filesearch/{store_id}/files/add')
async def add_vector_store_file(request: Request, store_id: str, file_id: str = Form(...)):
    login_required(request)
    try:
        client.vector_stores.files.create(store_id, file_id=file_id)
        flash(request, 'Файл добавлен')
    except Exception as e:
        flash_error(request, f'Ошибка: {e}')
    return RedirectResponse(request.url_for('view_vector_store', store_id=store_id), status_code=HTTP_302_FOUND)

@app.post('/filesearch/{store_id}/files/{file_id}/delete')
async def delete_vector_store_file(request: Request, store_id: str, file_id: str):
    login_required(request)
    try:
        client.vector_stores.files.delete(store_id, file_id)
        flash(request, 'Файл удалён')
    except Exception as e:
        flash_error(request, f'Ошибка: {e}')
    return RedirectResponse(request.url_for('view_vector_store', store_id=store_id), status_code=HTTP_302_FOUND)

# ----------------------- API endpoints -----------------------

# Assistants list
@app.get('/api/assistants')
async def api_assistants():
    """Return a list of all assistants."""
    try:
        assistants = client.beta.assistants.list(limit=100).data
        return {'assistants': [a.model_dump() for a in assistants]}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get('/api/assistants/{assistant_id}')
async def api_get_assistant(assistant_id: str):
    """Retrieve a single assistant."""
    try:
        assistant = client.beta.assistants.retrieve(assistant_id)
        return assistant.model_dump()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post('/api/create_thread')
async def api_create_thread():
    """Create a new thread."""
    try:
        thread = client.beta.threads.create()
        return {'thread_id': thread.id}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post('/api/threads/{thread_id}/messages')
async def api_add_message(thread_id: str, content: str = Form(...)):
    """Add a user message to a thread."""
    try:
        msg = client.beta.threads.messages.create(
            thread_id, role='user', content=content
        )
        return msg.model_dump()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get('/api/threads/{thread_id}/messages')
async def api_list_messages(thread_id: str):
    """List messages for a thread."""
    try:
        messages = client.beta.threads.messages.list(thread_id, order='asc').data
        return {'messages': [m.model_dump() for m in messages]}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post('/api/run')
async def api_run(thread_id: str = Form(...), assistant_id: str = Form(...)):
    """Start a run for a thread with the given assistant."""
    try:
        run = client.beta.threads.runs.create(
            thread_id=thread_id, assistant_id=assistant_id
        )
        return run.model_dump()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get('/api/thread_status/{run_id}')
async def api_thread_status(run_id: str, thread_id: str):
    """Get status information for a run."""
    try:
        run = client.beta.threads.runs.retrieve(run_id, thread_id=thread_id)
        return run.model_dump()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post('/api/threads/{thread_id}/runs/{run_id}/cancel')
async def api_cancel_run(thread_id: str, run_id: str):
    """Cancel a running thread."""
    try:
        run = client.beta.threads.runs.cancel(run_id, thread_id=thread_id)
        return run.model_dump()
    except Exception as e:
        raise HTTPException(500, str(e))

# ---------- Additional management endpoints ----------

@app.get('/api/models')
async def api_list_models():
    """Return available GPT models."""
    try:
        return {'models': list_gpt_models()}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post('/api/assistants')
async def api_create_assistant(
    name: str = Form(...),
    instructions: str = Form(''),
    model: str = Form('gpt-4o-mini'),
    temperature: float = Form(0.30),
    top_p: float = Form(0.15),
    vector_store_id: str = Form('')
):
    """Create a new assistant."""
    params = {
        'name': name,
        'instructions': instructions,
        'model': model,
        'temperature': temperature,
        'top_p': top_p,
    }
    tool_resources = {}
    if vector_store_id:
        tool_resources['file_search'] = {'vector_store_ids': [vector_store_id]}
    if tool_resources:
        params['tool_resources'] = tool_resources
    try:
        assistant = client.beta.assistants.create(**params)
        return assistant.model_dump()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.put('/api/assistants/{assistant_id}')
async def api_update_assistant(
    assistant_id: str,
    name: str = Form(None),
    instructions: str = Form(None),
    model: str = Form(None),
    temperature: float = Form(None),
    top_p: float = Form(None),
    vector_store_id: str = Form(None)
):
    """Update an existing assistant."""
    params = {}
    if name is not None:
        params['name'] = name
    if instructions is not None:
        params['instructions'] = instructions
    if model is not None:
        params['model'] = model
    if temperature is not None:
        params['temperature'] = temperature
    if top_p is not None:
        params['top_p'] = top_p
    if vector_store_id is not None:
        params['tool_resources'] = (
            {'file_search': {'vector_store_ids': [vector_store_id]}}
            if vector_store_id else {}
        )
    try:
        assistant = client.beta.assistants.update(assistant_id, **params)
        return assistant.model_dump()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete('/api/assistants/{assistant_id}')
async def api_delete_assistant(assistant_id: str):
    """Delete an assistant."""
    try:
        client.beta.assistants.delete(assistant_id)
        return {'deleted': assistant_id}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post('/api/assistants/{assistant_id}/files')
async def api_add_assistant_file(assistant_id: str, file_id: str = Form(...)):
    """Attach a file to an assistant's code interpreter."""
    try:
        assistant = client.beta.assistants.retrieve(assistant_id)
        tr = assistant.model_dump().get('tool_resources') or {}
        files = tr.get('code_interpreter', {}).get('file_ids', [])
        files.append(file_id)
        tr['code_interpreter'] = {'file_ids': files}
        client.beta.assistants.update(assistant_id, tool_resources=tr)
        return {'file_ids': files}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete('/api/assistants/{assistant_id}/files/{file_id}')
async def api_delete_assistant_file(assistant_id: str, file_id: str):
    """Remove a file from an assistant."""
    try:
        assistant = client.beta.assistants.retrieve(assistant_id)
        tr = assistant.model_dump().get('tool_resources') or {}
        files = tr.get('code_interpreter', {}).get('file_ids', [])
        if file_id in files:
            files.remove(file_id)
        tr['code_interpreter'] = {'file_ids': files}
        client.beta.assistants.update(assistant_id, tool_resources=tr)
        return {'file_ids': files}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get('/api/vector_stores')
async def api_vector_stores():
    """List File Search stores."""
    try:
        stores = client.vector_stores.list(limit=100).data
        return {'vector_stores': [s.model_dump() for s in stores]}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post('/api/vector_stores')
async def api_create_vector_store(name: str = Form(...), file_id: str = Form('')):
    """Create a new vector store."""
    params = {'name': name}
    if file_id:
        params['file_ids'] = [file_id]
    try:
        store = client.vector_stores.create(**params)
        return store.model_dump()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get('/api/vector_stores/{store_id}')
async def api_get_vector_store(store_id: str):
    """Retrieve a vector store."""
    try:
        store = client.vector_stores.retrieve(store_id)
        return store.model_dump()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete('/api/vector_stores/{store_id}')
async def api_delete_vector_store(store_id: str):
    """Delete a vector store."""
    try:
        client.vector_stores.delete(store_id)
        return {'deleted': store_id}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get('/api/vector_stores/{store_id}/files')
async def api_list_vector_store_files(store_id: str):
    """List files inside a vector store."""
    try:
        files = client.vector_stores.files.list(store_id, limit=100).data
        return {'files': [f.model_dump() for f in files]}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post('/api/vector_stores/{store_id}/files')
async def api_add_vector_store_file_api(store_id: str, file_id: str = Form(...)):
    """Add a file to a vector store."""
    try:
        file_obj = client.vector_stores.files.create(store_id, file_id=file_id)
        return file_obj.model_dump()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete('/api/vector_stores/{store_id}/files/{file_id}')
async def api_delete_vector_store_file_api(store_id: str, file_id: str):
    """Remove a file from a vector store."""
    try:
        client.vector_stores.files.delete(store_id, file_id)
        return {'deleted': file_id}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get('/api/threads/{thread_id}')
async def api_get_thread(thread_id: str):
    """Retrieve a thread."""
    try:
        thread = client.beta.threads.retrieve(thread_id)
        return thread.model_dump()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete('/api/threads/{thread_id}')
async def api_delete_thread(thread_id: str):
    """Delete a thread and its messages."""
    try:
        client.beta.threads.delete(thread_id)
        return {'deleted': thread_id}
    except Exception as e:
        raise HTTPException(500, str(e))


# ----------- Additional utility API endpoints -----------

@app.get('/api/billing')
async def api_billing():
    """Return billing information used on the dashboard."""
    return get_billing_data()


@app.post('/api/register')
async def api_register(username: str = Form(...), password: str = Form(...)):
    """Register a new user if registration is open."""
    if get_setting('registration_open', '1') != '1':
        raise HTTPException(403, 'Регистрация закрыта')
    with get_db() as db:
        try:
            db.execute(
                'INSERT INTO users (username, password) VALUES (?,?)',
                (username, generate_password_hash(password))
            )
            return {'registered': username}
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Пользователь уже существует')


@app.post('/api/login')
async def api_login_endpoint(
    request: Request, username: str = Form(...), password: str = Form(...)
):
    """Log in and start a session."""
    with get_db() as db:
        user = db.execute(
            'SELECT * FROM users WHERE username=?', (username,)
        ).fetchone()
    if not user or not check_password_hash(user['password'], password):
        raise HTTPException(401, 'Неверные учетные данные')
    request.session['user_id'] = user['id']
    return {'logged_in': username}


@app.post('/api/logout')
async def api_logout_endpoint(request: Request):
    """Log out the current user."""
    request.session.pop('user_id', None)
    return {'logged_out': True}


@app.get('/api/settings')
async def api_get_settings():
    """Return site settings."""
    return {
        'registration_open': get_setting('registration_open', '1') == '1'
    }


@app.put('/api/settings')
async def api_update_settings(registration_open: str = Form(None)):
    """Update the registration setting."""
    if registration_open is not None:
        set_setting(
            'registration_open',
            '1' if registration_open in ('1', 'true', 'on', 'True') else '0'
        )
    return {'registration_open': get_setting('registration_open', '1') == '1'}


@app.put('/api/password')
async def api_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...)
):
    """Change password for the current user."""
    login_required(request)
    with get_db() as db:
        user = db.execute(
            'SELECT * FROM users WHERE id=?', (request.session['user_id'],)
        ).fetchone()
        if not user or not check_password_hash(user['password'], current_password):
            raise HTTPException(403, 'Неверный текущий пароль')
        db.execute(
            'UPDATE users SET password=? WHERE id=?',
            (generate_password_hash(new_password), user['id'])
        )
    return {'updated': True}


@app.post('/api/assistants/{assistant_id}/chat')
async def api_assistant_chat(assistant_id: str, message: str = Form(...)):
    """Send one message to an assistant in a new temporary thread."""
    try:
        thread = client.beta.threads.create()
        client.beta.threads.messages.create(thread.id, role='user', content=message)
        run = client.beta.threads.runs.create(
            thread_id=thread.id, assistant_id=assistant_id
        )
        while run.status in ('queued', 'in_progress'):
            time.sleep(1)
            run = client.beta.threads.runs.retrieve(run.id, thread_id=thread.id)
        messages = client.beta.threads.messages.list(thread.id, order='asc').data
        return {
            'thread_id': thread.id,
            'messages': [m.model_dump() for m in messages]
        }
    except Exception as e:
        raise HTTPException(500, str(e))

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
