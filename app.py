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
    print(f"/api/script channel={channel} topic={topic} length={length_seconds}")

    if channel == 'kbites':
        prompt = f"""
First create a Korean short-form video script for the topic: {topic}.
Then create English translations for each of the four fields.

Return ONLY valid JSON with exactly these keys and no other text:
{{
  "title": "...",
  "description": "...",
  "narration": "...",
  "fixed_comment": "...",
  "title_en": "...",
  "description_en": "...",
  "narration_en": "...",
  "fixed_comment_en": "..."
}}

Requirements:
- The Korean fields (title, description, narration, fixed_comment) must be in Korean.
- The English fields (title_en, description_en, narration_en, fixed_comment_en) must be in English.
- The description field must contain a short body description of 2 to 3 sentences, then a newline, then exactly 10 relevant hashtags in Korean starting with #.
- The description_en field must contain a short body description of 2 to 3 sentences, then a newline, then exactly 10 relevant hashtags in English starting with #.
- The first sentence must be a strong hook using a question, twist, or surprising statement.
- Keep the audience curious until the end and make the script feel compelling.
- Make the narration about {length_seconds}s long.
- Base the content on verified facts when possible, using web search context and avoiding made-up claims.
- The Korean version should be catchy and natural for Korean viewers.
- The English version should be catchy and natural for an overseas audience.
- Do not wrap the JSON in markdown code fences.
- Do not include any extra commentary or explanation.
- 반드시 아래 JSON 형식으로만 응답하라. 다른 설명 절대 금지: {{"title":"...","description":"...","narration":"...","fixed_comment":"...","title_en":"...","description_en":"...","narration_en":"...","fixed_comment_en":"..."}}
"""
    else:
        prompt = f"""
한국어로 작성해 주세요. 모든 출력 필드(title, description, narration, fixed_comment)는 한국어여야 합니다.

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
- 한국어로 작성해 주세요. 모든 출력 필드(title, description, narration, fixed_comment)는 한국어여야 합니다.
- The description field must contain a short body description of 2 to 3 sentences, then a newline, then exactly 10 relevant hashtags in Korean starting with #.
- The first sentence must be a strong hook using a question, twist, or surprising statement
- Keep the audience curious until the end and make the script feel compelling
- Make the narration about 약 {length_seconds}초 분량
- Base the content on verified facts when possible, using web search context and avoiding made-up claims
- title should be catchy and clickable
- description should be natural and encourage comments
- fixed_comment should be short and engaging
- do not wrap the JSON in markdown code fences
- do not include any extra commentary or explanation
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
            'fixed_comment': parsed.get('fixed_comment', ''),
            'title_en': parsed.get('title_en', ''),
            'description_en': parsed.get('description_en', ''),
            'narration_en': parsed.get('narration_en', ''),
            'fixed_comment_en': parsed.get('fixed_comment_en', '')
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return {
            'title': '',
            'description': '',
            'narration': raw_text if 'raw_text' in locals() else 'No narration generated',
            'fixed_comment': '',
            'title_en': '',
            'description_en': '',
            'narration_en': '',
            'fixed_comment_en': ''
        }


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
