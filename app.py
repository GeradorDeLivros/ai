import os
from dotenv import load_dotenv
import time
import traceback
from flask import Flask, request, jsonify, send_file, Response
from together import Together
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
import io
import asyncio
from queue import Queue
import sqlite3
from datetime import datetime
# from flask_cors import CORS

load_dotenv()

app = Flask(__name__)
# CORS(app)

progress_queue = Queue()

TOGETHER_API_KEY = os.getenv('TOGETHER_API_KEY')

if not TOGETHER_API_KEY:
    raise ValueError("No Together API key found. Please set the TOGETHER_API_KEY environment variable.")

together_client = Together(api_key=TOGETHER_API_KEY)

async def generate_chunk(api, model, topic, current_word_count, language, is_new_chapter=False):
    if is_new_chapter:
        prompt = f"Write a detailed chapter for a book about {topic} in {language}. This is around word {current_word_count} of the book. Start with a chapter title, then write at least {current_word_count} words of content."
    else:
        prompt = f"Continue writing a detailed book about {topic} in {language}. This is around word {current_word_count} of the book. Write at least {current_word_count} words, ensuring the narrative flows smoothly from the previous section."
    
    try:
        response = together_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": f"You are an author writing a detailed book in {language}. Provide long, comprehensive responses with at least {current_word_count} words per chunk. Do not use asterisks (*) in the response text."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=5000,
            temperature=0.7,
            top_p=0.9,
            top_k=50,
            repetition_penalty=1.03,
            stop=None
        )
        generated_text = response.choices[0].message.content.strip()
        
        # Ensure minimum word count
        while len(generated_text.split()) < 500:
            additional_prompt = f"Continue the previous text, adding more details and expanding the narrative. Write at least {current_word_count} more words. Do not use asterisks (*) in the response text."
            additional_response = together_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": f"You are an author writing a detailed book in {language}. Provide long, comprehensive responses. Do not use asterisks (*) in the response text."},
                    {"role": "user", "content": generated_text},
                    {"role": "user", "content": additional_prompt}
                ],
                max_tokens=4000,
                temperature=0.7,
                top_p=0.9,
                top_k=50,
                repetition_penalty=1.03,
                stop=None
            )
            generated_text += "\n" + additional_response.choices[0].message.content.strip()
        
        return generated_text
    except Exception as e:
        print(f"An error occurred: {e}")
        await asyncio.sleep(60)
        return await generate_chunk(api, model, topic, current_word_count, language, is_new_chapter)

def create_pdf(content, title):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                            rightMargin=72, leftMargin=72,
                            topMargin=72, bottomMargin=18)

    styles = getSampleStyleSheet()
    
    font = 'Helvetica'
    
    styles.add(ParagraphStyle(name='Chapter',
                              fontName=font,
                              fontSize=18,
                              spaceAfter=12,
                              alignment=TA_CENTER))
    styles.add(ParagraphStyle(name='Content',
                              fontName=font,
                              fontSize=12,
                              spaceAfter=12,
                              alignment=TA_JUSTIFY))

    story = []

    story.append(Paragraph(title, styles['Title']))
    story.append(Spacer(1, 24))

    lines = content.split('\n')
    for line in lines:
        if line.strip().startswith("Chapter"):
            story.append(Spacer(1, 24))
            story.append(Paragraph(line.strip(), styles['Chapter']))
        else:
            story.append(Paragraph(line, styles['Content']))

    doc.build(story)
    buffer.seek(0)
    return buffer

def check_auth():
    auth_token = request.headers.get('Authorization')
    if not auth_token or auth_token != os.getenv('AUTHORIZATION'):
        return jsonify({"error": "Unauthorized"}), 401
    return None

@app.route('/generate', methods=['POST'])
async def generate_book():
    if not request.json:
        return jsonify({"error": "Request body must be JSON"}), 400
    
    auth_response = check_auth()
    if auth_response:
        return auth_response
    
    required_fields = ['topic', 'language', 'word_count']
    for field in required_fields:
        if field not in request.json:
            return jsonify({"error": f"Missing required field: {field}"}), 400
    
    topic = request.json['topic']
    language = request.json['language']
    target_word_count = request.json['word_count']
    
    if not isinstance(topic, str) or not topic.strip():
        return jsonify({"error": "Field 'topic' must be a non-empty string"}), 400
    
    if not isinstance(language, str) or not language.strip():
        return jsonify({"error": "Field 'language' must be a non-empty string"}), 400
    
    try:
        target_word_count = int(target_word_count)
        if target_word_count <= 0:
            raise ValueError
    except ValueError:
        return jsonify({"error": "Field 'word_count' must be a positive integer"}), 400
    
    api = 'together' 
    model = 'meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo'
    current_word_count = 0
    book_content = []
    chapter_count = 0

    tasks = []
    while current_word_count < target_word_count:
        is_new_chapter = (chapter_count == 0) or (current_word_count > 0 and current_word_count % 3000 < 500)
        
        if is_new_chapter:
            chapter_count += 1
            task = asyncio.create_task(generate_chunk(api, model, topic, current_word_count, language, is_new_chapter=True))
        else:
            task = asyncio.create_task(generate_chunk(api, model, topic, current_word_count, language))
        
        tasks.append(task)
        current_word_count += 500
        
        if len(tasks) >= 5 or current_word_count >= target_word_count:
            chunks = await asyncio.gather(*tasks)
            for chunk in chunks:
                book_content.append(chunk)
                actual_word_count = len(" ".join(book_content).split())
                progress_queue.put(actual_word_count)
            tasks = []
            await asyncio.sleep(1)

    formatted_book = "\n\n".join(book_content)
    actual_word_count = len(formatted_book.split())

    return jsonify({
        'content': formatted_book,
        'word_count': actual_word_count
    })


@app.route('/download-pdfx', methods=['POST'])
def download_pdf():

    auth_response = check_auth()
    if auth_response:
        return auth_response

    try:
        if not request.json:
            return jsonify({"error": "Request body must be JSON"}), 400
        
        if 'content' not in request.json or 'title' not in request.json:
            return jsonify({"error": "Missing required fields: 'content' and/or 'title'"}), 400
        
        content = request.json['content']
        title = request.json['title']
        
        if not isinstance(content, str) or not content.strip():
            return jsonify({"error": "Field 'content' must be a non-empty string"}), 400
        
        if not isinstance(title, str) or not title.strip():
            return jsonify({"error": "Field 'title' must be a non-empty string"}), 400
        
        pdf_buffer = create_pdf(content, title)
        
        ip = request.remote_addr
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{ip}_{timestamp}.pdf"
        filepath = os.path.join('saved_pdfs', filename)
        os.makedirs('saved_pdfs', exist_ok=True)
        with open(filepath, 'wb') as f:
            f.write(pdf_buffer.getvalue())
                
        return send_file(io.BytesIO(pdf_buffer.getvalue()), download_name=f"{title}.pdf", as_attachment=True, mimetype='application/pdf')
    
    except Exception as e:
        app.logger.error(f"PDF download error: {str(e)}")
        app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    
@app.route('/link-pdf', methods=['POST'])
def link_pdf():
    auth_response = check_auth()
    if auth_response:
        return auth_response

    try:
        if not request.json:
            return jsonify({"error": "Request body must be JSON"}), 400
        
        if 'content' not in request.json or 'title' not in request.json:
            return jsonify({"error": "Missing required fields: 'content' and/or 'title'"}), 400
        
        content = request.json['content']
        title = request.json['title']
        
        if not isinstance(content, str) or not content.strip():
            return jsonify({"error": "Field 'content' must be a non-empty string"}), 400
        
        if not isinstance(title, str) or not title.strip():
            return jsonify({"error": "Field 'title' must be a non-empty string"}), 400
        
        pdf_buffer = create_pdf(content, title)
        
        ip = request.remote_addr
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{ip}_{timestamp}.pdf"
        folder = 'saved_pdfs'
        filepath = os.path.join(folder, filename)
        os.makedirs(folder, exist_ok=True)
        
        with open(filepath, 'wb') as f:
            f.write(pdf_buffer.getvalue())
        
        return jsonify({"folder": folder, "filename": filename}), 200
    
    except Exception as e:
        app.logger.error(f"PDF download error: {str(e)}")
        app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/progress')
def progress():
    def generate(): 
        while True:
            if not progress_queue.empty():
                yield f"data: {progress_queue.get()}\n\n"
            else:
                yield "data: keep-alive\n\n"
            time.sleep(1)
    
    return Response(generate(), mimetype='text/event-stream')


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5151)