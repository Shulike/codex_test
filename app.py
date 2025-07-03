import os
import time
import sqlite3
from datetime import datetime, timedelta
import logging
from typing import Optional

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

@pass_context
def url_for(ctx, name: str, **path_params):
    request: Request = ctx['request']
    return request.url_for(name, **path_params)

templates = Jinja2Templates(directory='templates')
templates.env.globals['get_flashed_messages'] = get_flashed_messages
templates.env.globals['url_for'] = url_for

def current_user(request: Request):
    uid = request.session.get('user_id')
    if not uid:
        return None
    with get_db() as db:
        return db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()

def login_required(request: Request):
    if not request.session.get('user_id'):
        raise HTTPException(status_code=401)

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
    try:
        assistants = client.beta.assistants.list(limit=100).data
    except Exception as e:
        flash(request, f'Ошибка: {e}')
        assistants = []
    return templates.TemplateResponse('index.html', {
        'request': request,
        'title': 'Дашборд',
        'daily': billing['daily'],
        'total_usage': billing['total_usage'],
        'available': billing['available'],
        'assistants': assistants,
    })

@app.post('/generate')
async def generate(request: Request, prompt: str = Form(''), assistant_id: str = Form('')):
    if not prompt or not assistant_id:
        flash(request, 'Введите запрос и выберите ассистента')
        return RedirectResponse(request.url_for('index'), status_code=HTTP_302_FOUND)
    try:
        thread = client.beta.threads.create()
        client.beta.threads.messages.create(thread.id, role='user', content=prompt)
        run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=assistant_id)
        while run.status in ('queued','in_progress'):
            time.sleep(1)
            run = client.beta.threads.runs.retrieve(run.id, thread_id=thread.id)
        messages = client.beta.threads.messages.list(thread.id, order='asc').data
        answer = ''
        for m in messages:
            if m.role == 'assistant' and m.content:
                answer = m.content[0].text.value
        try:
            client.beta.threads.delete(thread.id)
        except Exception:
            pass
    except Exception as e:
        answer = f'Ошибка: {e}'
    billing = get_billing_data()
    if billing.get('error'):
        flash(request, f"Ошибка получения данных: {billing['error']}")
    try:
        assistants = client.beta.assistants.list(limit=100).data
    except Exception as e:
        flash(request, f'Ошибка: {e}')
        assistants = []
    return templates.TemplateResponse('index.html', {
        'request': request,
        'title': 'Дашборд',
        'daily': billing['daily'],
        'total_usage': billing['total_usage'],
        'available': billing['available'],
        'assistants': assistants,
        'prompt': prompt,
        'answer': answer,
        'selected_assistant': assistant_id,
    })

# Assistants management API
@app.get('/api/assistants')
async def api_assistants():
    try:
        assistants = client.beta.assistants.list(limit=100).data
        return {'assistants': [a.model_dump() for a in assistants]}
    except Exception as e:
        raise HTTPException(500, str(e))

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
