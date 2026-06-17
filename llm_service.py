"""Text LLM service. Providers: openai, deepseek, qwen."""
import json
import re
import requests

SYSTEM_PROMPT = (
    "You are a top-tier 小红书 (Xiaohongshu) copywriter. "
    "Given a topic or extracted content, write ONE viral-style 小红书 post in Simplified Chinese. "
    "Style: casual, intimate, emoji-rich, line breaks between thoughts, 第一人称, "
    "hook in the first line, end with a soft call-to-action. "
    "Return STRICT JSON with keys: title (catchy with emojis, <=20 chars), "
    "body (200-400 Chinese chars with emoji + linebreaks), hashtags (array of 5-10 strings each starting with #). "
    "No text outside the JSON."
)

IMAGE_PROMPT_SYSTEM = (
    "You craft concise English image-generation prompts for 小红书 cover images. "
    "Given a post title, body and topic, output ONE single-line English prompt (<=60 words) "
    "describing a vivid, photographic, 小红书-style cover image. No quotes, no extra text."
)


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r'^```(?:json)?', '', text).strip()
    text = re.sub(r'```$', '', text).strip()
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        raise ValueError('No JSON object in LLM response')
    return json.loads(m.group(0))


def _call_openai_chat(api_key, model, messages, base_url='https://api.openai.com/v1'):
    r = requests.post(
        f'{base_url}/chat/completions',
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json={'model': model, 'messages': messages, 'temperature': 0.8},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()['choices'][0]['message']['content']


def _call_text(provider, api_key, messages):
    p = (provider or '').lower()
    if p == 'openai':
        return _call_openai_chat(api_key, 'gpt-4o-mini', messages)
    if p == 'deepseek':
        return _call_openai_chat(api_key, 'deepseek-chat', messages, base_url='https://api.deepseek.com/v1')
    if p == 'qwen':
        return _call_openai_chat(api_key, 'qwen-plus', messages,
                                 base_url='https://dashscope.aliyuncs.com/compatible-mode/v1')
    raise ValueError(f'Unsupported text provider: {provider}')


def generate_post(provider, api_key, topic_or_output_a):
    if isinstance(topic_or_output_a, dict):
        user_content = '已提取素材如下:\n' + json.dumps(topic_or_output_a, ensure_ascii=False, indent=2)
    else:
        user_content = f'主题:{topic_or_output_a}'
    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': user_content},
    ]
    raw = _call_text(provider, api_key, messages)
    data = _extract_json(raw)
    tags = data.get('hashtags', [])
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r'[\s,，]+', tags) if t.strip()]
    tags = [t if t.startswith('#') else f'#{t}' for t in tags]
    return {
        'title': str(data.get('title', '')).strip(),
        'body': str(data.get('body', '')).strip(),
        'hashtags': tags,
    }


def build_image_prompt(provider, api_key, title, body, topic):
    messages = [
        {'role': 'system', 'content': IMAGE_PROMPT_SYSTEM},
        {'role': 'user', 'content': f'Title: {title}\nBody: {body}\nTopic: {topic}'},
    ]
    try:
        raw = _call_text(provider, api_key, messages).strip().strip('"').strip("'")
        return raw.split('\n')[0][:500]
    except Exception:
        return f'A bright, modern Xiaohongshu-style cover photo about: {title}. Soft lighting, vivid colors, lifestyle aesthetic.'


def parse_text_with_llm(provider, api_key, raw_text):
    sys = ('Extract structured info. Return STRICT JSON: '
           '{summary, key_points[], products_or_services[], tone}. No extra text.')
    messages = [
        {'role': 'system', 'content': sys},
        {'role': 'user', 'content': raw_text[:8000]},
    ]
    return _extract_json(_call_text(provider, api_key, messages))


def parse_image_with_llm(provider, api_key, image_b64, mime='image/jpeg'):
    p = (provider or '').lower()
    if p == 'openai':
        messages = [
            {'role': 'system', 'content': 'Return JSON {summary, key_points[], products_or_services[], tone}.'},
            {'role': 'user', 'content': [
                {'type': 'text', 'text': '提取图中关键信息,仅返回JSON。'},
                {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{image_b64}'}},
            ]},
        ]
        return _extract_json(_call_openai_chat(api_key, 'gpt-4o-mini', messages))
    if p == 'qwen':
        messages = [
            {'role': 'user', 'content': [
                {'type': 'text', 'text': '提取图中关键信息,返回JSON {summary, key_points[], products_or_services[], tone},仅JSON。'},
                {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{image_b64}'}},
            ]},
        ]
        return _extract_json(_call_openai_chat(api_key, 'qwen-vl-plus', messages,
                                               base_url='https://dashscope.aliyuncs.com/compatible-mode/v1'))
    return {'summary': '(vision not supported by this provider; switch to OpenAI or Qwen)',
            'key_points': [], 'products_or_services': [], 'tone': 'neutral'}


def test_text_key(provider, api_key):
    try:
        _call_text(provider, api_key, [{'role': 'user', 'content': 'ping'}])
        return True
    except Exception as e:
        print(f'test_text_key failed: {e}')
        return False
