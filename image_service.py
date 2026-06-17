"""Image generation. Providers: dalle, stability, wanxiang."""
import base64
import os
import time
import uuid
import requests

IMG_DIR = os.path.join(os.path.dirname(__file__), 'generated_images')
os.makedirs(IMG_DIR, exist_ok=True)


def _save_bytes(data, ext='png'):
    name = f'{int(time.time())}_{uuid.uuid4().hex[:8]}.{ext}'
    with open(os.path.join(IMG_DIR, name), 'wb') as f:
        f.write(data)
    return f'/generated_images/{name}'


def _save_from_url(url):
    r = requests.get(url, timeout=120); r.raise_for_status()
    return _save_bytes(r.content, 'png')


def _size_for(provider, aspect):
    aspect = aspect or '3:4'
    if provider == 'dalle':
        return '1024x1792' if aspect == '3:4' else '1024x1024'
    if provider == 'stability':
        return '768x1344' if aspect == '3:4' else '1024x1024'
    if provider == 'wanxiang':
        return '720x1280' if aspect == '3:4' else '1024x1024'
    return '1024x1024'


def _gen_dalle(api_key, prompt, aspect, count):
    size = _size_for('dalle', aspect)
    urls = []
    for _ in range(count):
        r = requests.post('https://api.openai.com/v1/images/generations',
                          headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                          json={'model': 'dall-e-3', 'prompt': prompt, 'n': 1, 'size': size}, timeout=180)
        r.raise_for_status()
        d = r.json()['data'][0]
        if 'url' in d: urls.append(_save_from_url(d['url']))
        elif 'b64_json' in d: urls.append(_save_bytes(base64.b64decode(d['b64_json']), 'png'))
    return urls


def _gen_stability(api_key, prompt, aspect, count):
    urls = []
    for _ in range(count):
        r = requests.post('https://api.stability.ai/v2beta/stable-image/generate/core',
                          headers={'Authorization': f'Bearer {api_key}', 'Accept': 'image/*'},
                          files={'none': ''},
                          data={'prompt': prompt, 'aspect_ratio': aspect or '3:4', 'output_format': 'png'},
                          timeout=180)
        r.raise_for_status()
        urls.append(_save_bytes(r.content, 'png'))
    return urls


def _gen_wanxiang(api_key, prompt, aspect, count):
    size = _size_for('wanxiang', aspect)
    submit = requests.post(
        'https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis',
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json',
                 'X-DashScope-Async': 'enable'},
        json={'model': 'wanx-v1', 'input': {'prompt': prompt},
              'parameters': {'size': size, 'n': max(1, min(count, 4))}}, timeout=60)
    submit.raise_for_status()
    task_id = submit.json()['output']['task_id']
    for _ in range(60):
        time.sleep(3)
        q = requests.get(f'https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}',
                         headers={'Authorization': f'Bearer {api_key}'}, timeout=30)
        q.raise_for_status()
        out = q.json().get('output', {})
        status = out.get('task_status')
        if status == 'SUCCEEDED':
            return [_save_from_url(r['url']) for r in out.get('results', []) if 'url' in r]
        if status in ('FAILED', 'UNKNOWN'):
            raise RuntimeError(f'wanxiang task failed: {out}')
    raise TimeoutError('wanxiang task timed out')


def generate_images(provider, api_key, prompt, aspect_ratio='3:4', count=1):
    p = (provider or '').lower()
    count = max(1, min(int(count or 1), 3))
    if p == 'dalle': return _gen_dalle(api_key, prompt, aspect_ratio, count)
    if p == 'stability': return _gen_stability(api_key, prompt, aspect_ratio, count)
    if p == 'wanxiang': return _gen_wanxiang(api_key, prompt, aspect_ratio, count)
    raise ValueError(f'Unsupported image provider: {provider}')


def test_image_key(provider, api_key):
    p = (provider or '').lower()
    try:
        if p == 'dalle':
            r = requests.get('https://api.openai.com/v1/models',
                             headers={'Authorization': f'Bearer {api_key}'}, timeout=20)
            return r.status_code == 200
        if p == 'stability':
            r = requests.get('https://api.stability.ai/v1/user/account',
                             headers={'Authorization': f'Bearer {api_key}'}, timeout=20)
            return r.status_code == 200
        if p == 'wanxiang':
            r = requests.post(
                'https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json',
                         'X-DashScope-Async': 'enable'},
                json={'model': 'wanx-v1', 'input': {'prompt': 'ping'},
                      'parameters': {'size': '1024x1024', 'n': 1}}, timeout=20)
            return r.status_code in (200, 202)
    except Exception as e:
        print(f'test_image_key failed: {e}')
    return False
