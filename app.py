import os
import requests
from flask import Flask, request, Response, render_template, stream_with_context

app = Flask(__name__, template_folder='templates')


@app.route('/')
def index():
    return render_template('index.html')


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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
