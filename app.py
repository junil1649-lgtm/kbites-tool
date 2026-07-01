import json
import os
import requests
from flask import Flask, Response, make_response, render_template, request, stream_with_context

app = Flask(__name__, template_folder='templates')


@app.route('/')
def index():
    response = make_response(render_template('index.html'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/api/voice', methods=['POST'])
def voice():
    api_key = os.environ.get('ELEVENLABS_API_KEY')
    voice_id = os.environ.get('ELEVENLABS_VOICE_ID')
    if not api_key or not voice_id:
        return {"error": "Missing ELEVENLABS_API_KEY or ELEVENLABS_VOICE_ID"}, 500

    data = request.get_json(silent=True) or {}
    text = data.get('text')
    if not text:
        return {"error": "No text provided"}, 400

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'Accept': 'audio/mpeg'
    }
    payload = {
        'text': text,
        'model': 'eleven_multilingual_v2'
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, stream=True, timeout=60)
    except requests.RequestException as e:
        return {"error": f"Request failed: {str(e)}"}, 502

    if resp.status_code != 200:
        body = resp.content
        ctype = resp.headers.get('content-type', 'text/plain')
        return Response(body, status=resp.status_code, content_type=ctype)

    return Response(stream_with_context(resp.iter_content(chunk_size=4096)), content_type=resp.headers.get('content-type', 'audio/mpeg'))


@app.route('/api/script', methods=['POST'])
def script():
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return {"error": "Missing ANTHROPIC_API_KEY"}, 500

    data = request.get_json(silent=True) or {}
    topic = (data.get('topic') or '').strip()
    channel = (data.get('channel') or 'dailyhint').strip().lower()
    length = (data.get('length') or '60').strip()
    if not topic:
        return {"error": "No topic provided"}, 400

    length_seconds = length if length in {'30', '45', '60', '90'} else '60'

    if channel == 'kbites':
        prompt = f"""
You are an expert short-form video script writer for overseas short-form video audiences.
Create a concise and engaging English short-form content script for the topic: {topic}

Return ONLY valid JSON with exactly these keys and no other text:
{{
  "title": "...",
  "description": "...",
  "narration": "...",
  "fixed_comment": "..."
}}

Requirements:
- English language only for title, description, narration, and fixed_comment
- The first sentence must be a strong hook using a question, twist, or surprising statement
- Keep the audience curious until the end and make the script feel compelling
- Make the narration about {length_seconds}s long
- Base the content on verified facts when possible, using web search context and avoiding made-up claims
- title should be catchy and clickable for a global audience
- description should be natural and encourage comments
- fixed_comment should be short and engaging
- do not wrap the JSON in markdown code fences
- do not include any extra commentary or explanation
"""
    else:
        prompt = f"""
You are an expert short-form video script writer for Korean short videos.
Create a concise and engaging Korean short-form content script for the topic: {topic}

Return ONLY valid JSON with exactly these keys and no other text:
{{
  "title": "...",
  "description": "...",
  "narration": "...",
  "fixed_comment": "..."
}}

Requirements:
- Korean language only for title, description, narration, and fixed_comment
- The first sentence must be a strong hook using a question, twist, or surprising statement
- Keep the audience curious until the end and make the script feel compelling
- Make the narration about 약 {length_seconds}초 분량
- Base the content on verified facts when possible, using web search context and avoiding made-up claims
- title should be catchy and clickable
- description should be natural and encourage comments
- fixed_comment should be short and engaging
- do not wrap the JSON in markdown code fences
- do not include any extra commentary or explanation
"""

    payload = {
        "model": "claude-sonnet-4-5",
        "max_tokens": 800,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}]
            }
        ],
        "tools": [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5
            }
        ]
    }

    try:
        resp = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
                'anthropic-beta': 'web-search-2025-03-05'
            },
            json=payload,
            timeout=60
        )
    except requests.RequestException as e:
        return {"error": f"Request failed: {str(e)}"}, 502

    if resp.status_code != 200:
        try:
            body = resp.json()
        except ValueError:
            body = {"error": resp.text}
        return {"error": body.get('error', {}).get('message', resp.text)}, resp.status_code

    try:
        data = resp.json()
        text_blocks = []
        for block in data.get('content', []):
            if block.get('type') == 'text':
                text_blocks.append(block.get('text', ''))
        raw_text = ''.join(text_blocks).strip()

        if raw_text.startswith('```'):
            raw_text = raw_text.strip('`').strip()
            if raw_text.lower().startswith('json'):
                raw_text = raw_text[4:].strip()

        if raw_text.startswith('{') and raw_text.endswith('}'):
            parsed = json.loads(raw_text)
        else:
            start = raw_text.find('{')
            end = raw_text.rfind('}')
            if start != -1 and end != -1 and end > start:
                candidate = raw_text[start:end + 1]
                parsed = json.loads(candidate)
            else:
                return {
                    'title': '',
                    'description': '',
                    'narration': raw_text or 'No narration generated',
                    'fixed_comment': ''
                }

        return {
            'title': parsed.get('title', ''),
            'description': parsed.get('description', ''),
            'narration': parsed.get('narration', ''),
            'fixed_comment': parsed.get('fixed_comment', '')
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return {
            'title': '',
            'description': '',
            'narration': raw_text if 'raw_text' in locals() else 'No narration generated',
            'fixed_comment': ''
        }


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
