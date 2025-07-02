import os
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'change-me')

openai_api_key = os.environ.get('OPENAI_API_KEY')

if not openai_api_key:
    raise RuntimeError("OPENAI_API_KEY environment variable not set")

client = OpenAI(api_key=openai_api_key)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    prompt = request.form.get('prompt', '')
    if not prompt:
        flash('Введите запрос')
        return redirect(url_for('index'))

    try:
        response = client.chat.completions.create(
            model='gpt-3.5-turbo',
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=150
        )
        answer = response.choices[0].message.content
    except Exception as e:
        answer = f'Ошибка: {e}'
    return render_template('index.html', prompt=prompt, answer=answer)


@app.route('/assistants')
def list_assistants():
    assistants = client.beta.assistants.list().data
    return render_template('assistants.html', assistants=assistants)


@app.route('/assistants/new', methods=['GET', 'POST'])
def new_assistant():
    if request.method == 'POST':
        name = request.form.get('name')
        instructions = request.form.get('instructions')
        model = request.form.get('model', 'gpt-3.5-turbo-1106')
        temperature = float(request.form.get('temperature', 0))
        try:
            client.beta.assistants.create(
                name=name,
                instructions=instructions,
                model=model,
                temperature=temperature,
            )
            flash('Ассистент создан')
            return redirect(url_for('list_assistants'))
        except Exception as e:
            flash(f'Ошибка: {e}')
    return render_template('new_assistant.html')


@app.route('/assistants/<assistant_id>/edit', methods=['GET', 'POST'])
def edit_assistant(assistant_id):
    try:
        assistant = client.beta.assistants.retrieve(assistant_id)
        files = client.beta.assistants.files.list(assistant_id).data
    except Exception as e:
        flash(f'Ошибка: {e}')
        return redirect(url_for('list_assistants'))

    if request.method == 'POST':
        name = request.form.get('name')
        instructions = request.form.get('instructions')
        model = request.form.get('model')
        temperature = float(request.form.get('temperature', 0))
        try:
            client.beta.assistants.update(
                assistant_id,
                name=name,
                instructions=instructions,
                model=model,
                temperature=temperature,
            )
            flash('Ассистент обновлён')
            return redirect(url_for('edit_assistant', assistant_id=assistant_id))
        except Exception as e:
            flash(f'Ошибка: {e}')

    return render_template(
        'edit_assistant.html', assistant=assistant, files=files
    )


@app.route('/assistants/<assistant_id>/delete', methods=['POST'])
def delete_assistant(assistant_id):
    try:
        client.beta.assistants.delete(assistant_id)
        flash('Ассистент удалён')
    except Exception as e:
        flash(f'Ошибка: {e}')
    return redirect(url_for('list_assistants'))


@app.route('/assistants/<assistant_id>/files/add', methods=['POST'])
def add_file(assistant_id):
    file_id = request.form.get('file_id')
    try:
        client.beta.assistants.files.create(assistant_id, file_id=file_id)
        flash('Файл добавлен')
    except Exception as e:
        flash(f'Ошибка: {e}')
    return redirect(url_for('edit_assistant', assistant_id=assistant_id))


@app.route('/assistants/<assistant_id>/files/<file_id>/delete', methods=['POST'])
def delete_file(assistant_id, file_id):
    try:
        client.beta.assistants.files.delete(assistant_id, file_id)
        flash('Файл удалён')
    except Exception as e:
        flash(f'Ошибка: {e}')
    return redirect(url_for('edit_assistant', assistant_id=assistant_id))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
