import json
import os
import re
import requests
from flask import Flask, Response, make_response, render_template, request, stream_with_context

app = Flask(__name__, template_folder='templates')


def extract_json_object(text):
    if not text:
        return None

    cleaned = text.strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.strip('`').strip()
        if cleaned.lower().startswith('json'):
            cleaned = cleaned[4:].strip()

    start = cleaned.find('{')
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return cleaned[start:index + 1]

    return None


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
    print(f"/api/script channel={channel} topic={topic} length={length_seconds}")

    prompt = f"""
Create a Korean short-form video script for the topic: {topic}.

Return ONLY valid JSON with exactly these keys and no other text:
{{
  "title": "...",
  "description": "...",
  "narration": "...",
  "fixed_comment": "..."
}}

Requirements:
- All output fields must be in Korean.
- If the channel is K-Bites, write from the perspective of someone introducing Korea to foreigners, not from the perspective of a Korean speaking to other Koreans.
- Use an outsider-friendly tone that explains Korea in a fresh way for international viewers.
- The first sentence must be a strong hook using a question, twist, or surprising statement.
- Keep the audience curious until the end and make the script feel compelling.
- Make the narration about 약 {length_seconds}초 분량.
- The description field must contain a short body description of 2 to 3 sentences, then a newline, then exactly 10 relevant hashtags in Korean starting with #.
- Base the content on verified facts when possible, using web search context and avoiding made-up claims.
- Do not wrap the JSON in markdown code fences.
- Do not include any extra commentary or explanation.
- Output ONLY the raw JSON object. No explanation before or after. No markdown code fences.
- 반드시 아래 JSON 형식으로만 응답하라. 다른 설명 절대 금지: {{"title":"...","description":"...","narration":"...","fixed_comment":"..."}}
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
        content_blocks = data.get('content', [])
        text_blocks = [block.get('text', '') for block in content_blocks if block.get('type') == 'text']
        raw_text = ''
        if text_blocks:
            raw_text = text_blocks[-1].strip()

        candidate = extract_json_object(raw_text)
        if candidate:
            parsed = json.loads(candidate)
        else:
            return {
                'title': '',
                'description': '',
                'narration': raw_text or 'No narration generated',
                'fixed_comment': '',
                'title_en': '',
                'description_en': '',
                'narration_en': '',
                'fixed_comment_en': ''
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


@app.route('/api/translate', methods=['POST'])
def translate():
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return {"error": "Missing ANTHROPIC_API_KEY"}, 500

    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    description = (data.get('description') or '').strip()
    narration = (data.get('narration') or '').strip()
    fixed_comment = (data.get('fixed_comment') or '').strip()

    if not all([title, description, narration, fixed_comment]):
        return {"error": "Missing script fields"}, 400

    prompt = f"""
Translate the following Korean short-form video script fields into English.
Do not create new content. Only translate the existing meaning.

Return ONLY valid JSON with exactly these keys and no other text:
{{
  "title_en": "...",
  "description_en": "...",
  "narration_en": "...",
  "fixed_comment_en": "..."
}}

Fields:
title: {title}
description: {description}
narration: {narration}
fixed_comment: {fixed_comment}

Requirements:
- Translate into natural English.
- Keep the same meaning and tone.
- The description_en field should contain a short body description of 2 to 3 sentences, then a newline, then exactly 10 relevant hashtags in English starting with #.
- Do not wrap the JSON in markdown code fences.
- Do not include any extra commentary or explanation.
- Output ONLY the raw JSON object. No explanation before or after. No markdown code fences.
- 반드시 아래 JSON 형식으로만 응답하라. 다른 설명 절대 금지: {{"title_en":"...","description_en":"...","narration_en":"...","fixed_comment_en":"..."}}
"""

    payload = {
        "model": "claude-sonnet-4-5",
        "max_tokens": 800,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}]
            }
        ]
    }

    try:
        resp = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
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
        content_blocks = data.get('content', [])
        text_blocks = [block.get('text', '') for block in content_blocks if block.get('type') == 'text']
        raw_text = text_blocks[-1].strip() if text_blocks else ''
        candidate = extract_json_object(raw_text)
        if candidate:
            parsed = json.loads(candidate)
        else:
            return {"error": "Failed to parse translation output"}, 502

        return {
            'title_en': parsed.get('title_en', ''),
            'description_en': parsed.get('description_en', ''),
            'narration_en': parsed.get('narration_en', ''),
            'fixed_comment_en': parsed.get('fixed_comment_en', '')
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return {"error": "Failed to parse translation output"}, 502


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
