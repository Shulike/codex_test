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

# Needed for vector stores and other beta features
client = OpenAI(
    api_key=openai_api_key,
    default_headers={"OpenAI-Beta": "assistants=v2"},
)

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
    default_model = 'gpt-4o-mini'
    try:
        models = [m.id for m in client.models.list().data if m.id.startswith('gpt')]
        vector_stores = client.vector_stores.list().data
    except Exception:
        models = ['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo', 'gpt-3.5-turbo-1106']
        vector_stores = []

    if request.method == 'POST':
        name = request.form.get('name')
        instructions = request.form.get('instructions')
        model = request.form.get('model', default_model)
        temperature = float(request.form.get('temperature', 0.3))
        top_p = float(request.form.get('top_p', 0.15))
        vector_store_id = request.form.get('vector_store_id') or None
        try:
            tools = []
            tool_resources = {}
            if vector_store_id:
                tools.append({"type": "file_search"})
                tool_resources = {"file_search": {"vector_store_ids": [vector_store_id]}}
            client.beta.assistants.create(
                name=name,
                instructions=instructions,
                model=model,
                temperature=temperature,
                top_p=top_p,
                tools=tools,
                tool_resources=tool_resources,
            )
            flash('Ассистент создан')
            return redirect(url_for('list_assistants'))
        except Exception as e:
            flash(f'Ошибка: {e}')
    return render_template('new_assistant.html', models=models, default_model=default_model, vector_stores=vector_stores)


@app.route('/assistants/<assistant_id>/edit', methods=['GET', 'POST'])
def edit_assistant(assistant_id):
    try:
        assistant = client.beta.assistants.retrieve(assistant_id)
        files = client.beta.assistants.files.list(assistant_id).data
        models = [m.id for m in client.models.list().data if m.id.startswith('gpt')]
        vector_stores = client.vector_stores.list().data
    except Exception as e:
        flash(f'Ошибка: {e}')
        return redirect(url_for('list_assistants'))

    if request.method == 'POST':
        name = request.form.get('name')
        instructions = request.form.get('instructions')
        model = request.form.get('model')
        temperature = float(request.form.get('temperature', 0.3))
        top_p = float(request.form.get('top_p', 0.15))
        vector_store_id = request.form.get('vector_store_id') or None
        try:
            update_kwargs = dict(
                name=name,
                instructions=instructions,
                model=model,
                temperature=temperature,
                top_p=top_p,
            )
            if vector_store_id:
                update_kwargs["tools"] = [{"type": "file_search"}]
                update_kwargs["tool_resources"] = {
                    "file_search": {"vector_store_ids": [vector_store_id]}
                }
            client.beta.assistants.update(
                assistant_id,
                **update_kwargs,
            )
            flash('Ассистент обновлён')
            return redirect(url_for('edit_assistant', assistant_id=assistant_id))
        except Exception as e:
            flash(f'Ошибка: {e}')

    try:
        selected_vector_store = assistant.tool_resources.file_search.vector_store_ids[0]
    except Exception:
        selected_vector_store = ''

    return render_template(
        'edit_assistant.html',
        assistant=assistant,
        files=files,
        models=models,
        vector_stores=vector_stores,
        selected_vector_store=selected_vector_store,
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


@app.route('/filesearch')
def list_vector_stores():
    try:
        vector_stores = client.vector_stores.list().data
    except Exception as e:
        flash(f'Ошибка: {e}')
        vector_stores = []
    return render_template('vector_stores.html', vector_stores=vector_stores)


@app.route('/filesearch/new', methods=['GET', 'POST'])
def new_vector_store():
    if request.method == 'POST':
        name = request.form.get('name')
        file_id = request.form.get('file_id')
        try:
            kwargs = {"name": name}
            if file_id:
                kwargs["file_ids"] = [file_id]
            client.vector_stores.create(**kwargs)
            flash('File Search создан')
            return redirect(url_for('list_vector_stores'))
        except Exception as e:
            flash(f'Ошибка: {e}')
    return render_template('new_vector_store.html')


@app.route('/filesearch/<vs_id>')
def view_vector_store(vs_id):
    try:
        vector_store = client.vector_stores.retrieve(vs_id)
        files = client.vector_stores.files.list(vs_id).data
    except Exception as e:
        flash(f'Ошибка: {e}')
        return redirect(url_for('list_vector_stores'))
    return render_template('view_vector_store.html', vector_store=vector_store, files=files)


@app.route('/filesearch/<vs_id>/delete', methods=['POST'])
def delete_vector_store(vs_id):
    try:
        client.vector_stores.delete(vs_id)
        flash('File Search удалён')
    except Exception as e:
        flash(f'Ошибка: {e}')
    return redirect(url_for('list_vector_stores'))


@app.route('/filesearch/<vs_id>/files/add', methods=['POST'])
def add_vector_store_file(vs_id):
    file_id = request.form.get('file_id')
    try:
        client.vector_stores.files.create(vs_id, file_id=file_id)
        flash('Файл добавлен')
    except Exception as e:
        flash(f'Ошибка: {e}')
    return redirect(url_for('view_vector_store', vs_id=vs_id))


@app.route('/filesearch/<vs_id>/files/<file_id>/delete', methods=['POST'])
def delete_vector_store_file(vs_id, file_id):
    try:
        client.vector_stores.files.delete(vs_id, file_id)
        flash('Файл удалён')
    except Exception as e:
        flash(f'Ошибка: {e}')
    return redirect(url_for('view_vector_store', vs_id=vs_id))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
