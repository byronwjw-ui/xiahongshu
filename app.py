"""Xiaohongshu copywriting + image generator — Flask backend.

LLM API keys are NEVER hardcoded and NEVER read from .env.
Users paste them in /settings and they are stored encrypted in the DB.
"""
import base64
import io
import json
import os
import random
import secrets
from functools import wraps

import bcrypt
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory, redirect, abort
from flask_cors import CORS

from models import db, User, ApiKey, SystemKey, Post
import mail_service
import llm_service
import image_service

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
GEN_DIR = os.path.join(BASE_DIR, 'generated_images')
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(GEN_DIR, exist_ok=True)

ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.pdf', '.doc', '.docx'}
MAX_BYTES = 10 * 1024 * 1024

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(BASE_DIR, "database.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = MAX_BYTES

db.init_app(app)

# ---- Encryption (Fernet) ----------------------------------------------------
# Key derived from SECRET_KEY so it survives restarts; can be overridden by FERNET_KEY.
def _fernet():
    raw = os.getenv('FERNET_KEY')
    if not raw:
        import hashlib
        digest = hashlib.sha256(app.config['SECRET_KEY'].encode()).digest()
        raw = base64.urlsafe_b64encode(digest).decode()
    return Fernet(raw.encode() if isinstance(raw, str) else raw)


def enc(s: str) -> bytes:
    if not s:
        return b''
    return _fernet().encrypt(s.encode())


def dec(b: bytes) -> str:
    if not b:
        return ''
    try:
        return _fernet().decrypt(b).decode()
    except Exception:
        return ''


def mask(s: str) -> str:
    if not s:
        return ''
    if len(s) <= 8:
        return '*' * len(s)
    return s[:4] + '*' * (len(s) - 8) + s[-4:]

# ---- Auth helpers -----------------------------------------------------------
def current_user():
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '').strip() or request.args.get('token', '')
    if not token:
        return None
    return User.query.filter_by(token=token).first()


def login_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        u = current_user()
        if not u:
            return jsonify({'error': 'unauthorized'}), 401
        request.user = u
        return f(*a, **kw)
    return wrap


def admin_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        u = current_user()
        if not u or u.role != 'admin':
            return jsonify({'error': 'forbidden'}), 403
        request.user = u
        return f(*a, **kw)
    return wrap


def get_effective_keys(user: User):
    """Return (text_provider, text_key, image_provider, image_key) with system fallback."""
    tp = tk = ip = ik = None
    if user.keys:
        tp = user.keys.text_provider
        tk = dec(user.keys.text_key_enc) if user.keys.text_key_enc else None
        ip = user.keys.image_provider
        ik = dec(user.keys.image_key_enc) if user.keys.image_key_enc else None
    if not tk or not ik:
        sys_k = SystemKey.query.first()
        if sys_k:
            if not tk and sys_k.text_key_enc:
                tp = tp or sys_k.text_provider
                tk = dec(sys_k.text_key_enc)
            if not ik and sys_k.image_key_enc:
                ip = ip or sys_k.image_provider
                ik = dec(sys_k.image_key_enc)
    return tp, tk, ip, ik

# ---- Static pages -----------------------------------------------------------
@app.route('/')
def root():
    return send_from_directory('static', 'index.html')


@app.route('/settings')
def settings_page():
    return send_from_directory('static', 'settings.html')


@app.route('/admin')
def admin_page():
    return send_from_directory('static', 'admin.html')


@app.route('/generated_images/<path:fname>')
def serve_generated(fname):
    return send_from_directory(GEN_DIR, fname)


@app.route('/uploads/<path:fname>')
def serve_upload(fname):
    return send_from_directory(UPLOAD_DIR, fname)

# ---- Auth routes ------------------------------------------------------------
@app.post('/api/register')
def register():
    data = request.get_json(force=True)
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if not email or not password:
        return jsonify({'error': 'email and password required'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'email already registered'}), 400
    code = f'{random.randint(100000, 999999)}'
    u = User(
        email=email,
        password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()),
        verify_code=code,
        verified=False,
        role='user',
    )
    db.session.add(u); db.session.commit()
    mail_service.send_email(email, '小红书生成器 - 验证码', f'你的验证码: {code}')
    return jsonify({'ok': True, 'message': 'verification code sent (check console / mail.log)'})


@app.post('/api/verify')
def verify():
    data = request.get_json(force=True)
    email = (data.get('email') or '').strip().lower()
    code = (data.get('code') or '').strip()
    u = User.query.filter_by(email=email).first()
    if not u or u.verify_code != code:
        return jsonify({'error': 'invalid code'}), 400
    u.verified = True
    u.verify_code = None
    u.new_token()
    db.session.commit()
    return jsonify({'ok': True, 'token': u.token, 'user': u.to_dict()})


@app.post('/api/login')
def login():
    data = request.get_json(force=True)
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    u = User.query.filter_by(email=email).first()
    if not u or not bcrypt.checkpw(password.encode(), u.password_hash):
        return jsonify({'error': 'invalid credentials'}), 400
    if not u.verified:
        return jsonify({'error': 'email not verified', 'need_verify': True}), 403
    u.new_token(); db.session.commit()
    return jsonify({'ok': True, 'token': u.token, 'user': u.to_dict()})


@app.get('/api/me')
@login_required
def me():
    return jsonify({'user': request.user.to_dict()})

# ---- API key routes ---------------------------------------------------------
@app.get('/api/keys')
@login_required
def get_keys():
    u = request.user
    k = u.keys
    out = {
        'text_provider': k.text_provider if k else 'openai',
        'image_provider': k.image_provider if k else 'dalle',
        'text_key_masked': mask(dec(k.text_key_enc)) if (k and k.text_key_enc) else '',
        'image_key_masked': mask(dec(k.image_key_enc)) if (k and k.image_key_enc) else '',
        'text_set': bool(k and k.text_key_enc),
        'image_set': bool(k and k.image_key_enc),
    }
    sys_k = SystemKey.query.first()
    out['system_text_fallback'] = bool(sys_k and sys_k.text_key_enc)
    out['system_image_fallback'] = bool(sys_k and sys_k.image_key_enc)
    return jsonify(out)


@app.post('/api/keys')
@login_required
def save_keys():
    u = request.user
    data = request.get_json(force=True)
    k = u.keys or ApiKey(user_id=u.id)
    if 'text_provider' in data: k.text_provider = data['text_provider']
    if 'image_provider' in data: k.image_provider = data['image_provider']
    if data.get('text_key'): k.text_key_enc = enc(data['text_key'])
    if data.get('image_key'): k.image_key_enc = enc(data['image_key'])
    db.session.add(k); db.session.commit()
    return jsonify({'ok': True})


@app.post('/api/keys/test')
@login_required
def test_keys():
    u = request.user
    data = request.get_json(force=True)
    which = data.get('which', 'text')
    # Allow testing freshly typed key without saving first.
    if which == 'text':
        provider = data.get('text_provider') or (u.keys.text_provider if u.keys else None)
        key = data.get('text_key') or (dec(u.keys.text_key_enc) if (u.keys and u.keys.text_key_enc) else None)
        if not provider or not key:
            return jsonify({'ok': False, 'error': 'no key/provider'}), 400
        return jsonify({'ok': llm_service.test_text_key(provider, key)})
    else:
        provider = data.get('image_provider') or (u.keys.image_provider if u.keys else None)
        key = data.get('image_key') or (dec(u.keys.image_key_enc) if (u.keys and u.keys.image_key_enc) else None)
        if not provider or not key:
            return jsonify({'ok': False, 'error': 'no key/provider'}), 400
        return jsonify({'ok': image_service.test_image_key(provider, key)})

# ---- Upload / parsing -------------------------------------------------------
@app.post('/api/upload')
@login_required
def upload():
    u = request.user
    f = request.files.get('file')
    if not f:
        return jsonify({'error': 'no file'}), 400
    name = f.filename or 'upload'
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({'error': f'unsupported extension {ext}'}), 400
    safe_name = f'{secrets.token_hex(6)}{ext}'
    save_path = os.path.join(UPLOAD_DIR, safe_name)
    f.save(save_path)

    tp, tk, _, _ = get_effective_keys(u)
    if not tk:
        return jsonify({'error': 'text LLM key not set', 'redirect': '/settings'}), 400

    try:
        if ext in ('.jpg', '.jpeg', '.png'):
            with open(save_path, 'rb') as fp:
                b64 = base64.b64encode(fp.read()).decode()
            mime = 'image/png' if ext == '.png' else 'image/jpeg'
            output_a = llm_service.parse_image_with_llm(tp, tk, b64, mime)
        elif ext == '.pdf':
            import fitz  # PyMuPDF
            doc = fitz.open(save_path)
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes('png')
            doc.close()
            b64 = base64.b64encode(img_bytes).decode()
            output_a = llm_service.parse_image_with_llm(tp, tk, b64, 'image/png')
        elif ext in ('.doc', '.docx'):
            from docx import Document
            doc = Document(save_path)
            text = '\n'.join(p.text for p in doc.paragraphs)
            output_a = llm_service.parse_text_with_llm(tp, tk, text)
        else:
            output_a = {'summary': '', 'key_points': [], 'products_or_services': [], 'tone': 'neutral'}
    except Exception as e:
        return jsonify({'error': f'parse failed: {e}'}), 500

    return jsonify({'ok': True, 'output_a': output_a, 'file': f'/uploads/{safe_name}'})

# ---- Generation -------------------------------------------------------------
@app.post('/api/generate/text')
@login_required
def generate_text():
    u = request.user
    data = request.get_json(force=True)
    tp, tk, ip, _ = get_effective_keys(u)
    if not tk or not tp:
        return jsonify({'error': 'text LLM key not set', 'redirect': '/settings'}), 400
    topic = data.get('topic')
    output_a = data.get('output_a')
    payload = output_a if output_a else (topic or '')
    if not payload:
        return jsonify({'error': 'topic or output_a required'}), 400
    try:
        result = llm_service.generate_post(tp, tk, payload)
    except Exception as e:
        return jsonify({'error': f'text generation failed: {e}'}), 500
    # also draft an image prompt
    image_prompt = llm_service.build_image_prompt(tp, tk, result['title'], result['body'], str(topic or ''))
    result['image_prompt'] = image_prompt
    return jsonify({'ok': True, **result})


@app.post('/api/generate/image')
@login_required
def generate_image():
    u = request.user
    data = request.get_json(force=True)
    _, _, ip, ik = get_effective_keys(u)
    if not ik or not ip:
        return jsonify({'error': 'image LLM key not set', 'redirect': '/settings'}), 400
    prompt = (data.get('prompt') or '').strip()
    if not prompt:
        return jsonify({'error': 'prompt required'}), 400
    aspect = data.get('aspect_ratio') or '3:4'
    count = int(data.get('count') or 1)
    try:
        urls = image_service.generate_images(ip, ik, prompt, aspect, count)
    except Exception as e:
        return jsonify({'error': f'image generation failed: {e}'}), 500
    return jsonify({'ok': True, 'images': urls})

# ---- Posts CRUD -------------------------------------------------------------
@app.get('/api/posts')
@login_required
def list_posts():
    u = request.user
    posts = Post.query.filter_by(user_id=u.id).order_by(Post.updated_at.desc()).all()
    return jsonify({'posts': [p.to_dict() for p in posts]})


@app.post('/api/posts')
@login_required
def save_post():
    u = request.user
    data = request.get_json(force=True)
    pid = data.get('id')
    p = Post.query.filter_by(id=pid, user_id=u.id).first() if pid else None
    if not p:
        p = Post(user_id=u.id)
    p.topic = data.get('topic', p.topic)
    p.title = data.get('title', p.title)
    p.body = data.get('body', p.body)
    if 'hashtags' in data: p.hashtags = json.dumps(data['hashtags'], ensure_ascii=False)
    if 'image_prompt' in data: p.image_prompt = data['image_prompt']
    if 'images' in data: p.images = json.dumps(data['images'], ensure_ascii=False)
    db.session.add(p); db.session.commit()
    return jsonify({'ok': True, 'post': p.to_dict()})


@app.delete('/api/posts/<int:pid>')
@login_required
def delete_post(pid):
    u = request.user
    p = Post.query.filter_by(id=pid, user_id=u.id).first()
    if not p: return jsonify({'error': 'not found'}), 404
    db.session.delete(p); db.session.commit()
    return jsonify({'ok': True})

# ---- Admin ------------------------------------------------------------------
@app.get('/api/admin/users')
@admin_required
def admin_users():
    return jsonify({'users': [u.to_dict() for u in User.query.order_by(User.created_at.desc()).all()]})


@app.get('/api/admin/posts')
@admin_required
def admin_posts():
    rows = []
    for p in Post.query.order_by(Post.updated_at.desc()).all():
        d = p.to_dict()
        d['user_email'] = p.user.email if p.user else None
        rows.append(d)
    return jsonify({'posts': rows})


@app.delete('/api/admin/users/<int:uid>')
@admin_required
def admin_del_user(uid):
    u = User.query.get(uid)
    if not u: return jsonify({'error': 'not found'}), 404
    if u.role == 'admin': return jsonify({'error': 'cannot delete admin'}), 400
    db.session.delete(u); db.session.commit()
    return jsonify({'ok': True})


@app.delete('/api/admin/posts/<int:pid>')
@admin_required
def admin_del_post(pid):
    p = Post.query.get(pid)
    if not p: return jsonify({'error': 'not found'}), 404
    db.session.delete(p); db.session.commit()
    return jsonify({'ok': True})


@app.get('/api/admin/system-keys')
@admin_required
def admin_get_system_keys():
    s = SystemKey.query.first()
    if not s:
        return jsonify({'text_provider': 'openai', 'image_provider': 'dalle',
                        'text_key_masked': '', 'image_key_masked': '',
                        'text_set': False, 'image_set': False})
    return jsonify({
        'text_provider': s.text_provider or 'openai',
        'image_provider': s.image_provider or 'dalle',
        'text_key_masked': mask(dec(s.text_key_enc)) if s.text_key_enc else '',
        'image_key_masked': mask(dec(s.image_key_enc)) if s.image_key_enc else '',
        'text_set': bool(s.text_key_enc),
        'image_set': bool(s.image_key_enc),
    })


@app.post('/api/admin/system-keys')
@admin_required
def admin_set_system_keys():
    data = request.get_json(force=True)
    s = SystemKey.query.first() or SystemKey()
    if 'text_provider' in data: s.text_provider = data['text_provider']
    if 'image_provider' in data: s.image_provider = data['image_provider']
    if data.get('text_key'): s.text_key_enc = enc(data['text_key'])
    if data.get('image_key'): s.image_key_enc = enc(data['image_key'])
    db.session.add(s); db.session.commit()
    return jsonify({'ok': True})

# ---- Seed -------------------------------------------------------------------
DEMO_POSTS = [
    {
        'topic': '成都按摩店探店 - 十足道锦江店',
        'title': '💅成都探店 | 十足道锦江店太舏服了吧！',
        'body': '姐妹们我又来探店啦～\n\n这次去的是锦江店📍\n门店超级干净温馨的中式风\u3002\n按摩师手法超专业👍\n肩颈被揉开的那一刻真的升天✨\n\n推荐项目：中式推拿90分钟\n价格友好，服务超赞。\n上班族姐妹们冲子啊！',
        'hashtags': ['#成都探店', '#按摩推拿', '#十足道', '#锦江区', '#养生', '#肩颈放松'],
        'image_prompt': 'A cozy, warm-lit Chinese-style massage parlor entrance in Chengdu, soft amber lighting, wooden interior, lifestyle photography, Xiaohongshu aesthetic',
        'images': ['https://images.unsplash.com/photo-1544161515-4ab6ce6db874?w=800'],
    },
    {
        'topic': '周末养生推拿特惠 98 元',
        'title': '🎉周末仅限！推拿养生98元拿下',
        'body': '寶贝们这个周末有福啦🎁\n\n原价268的全身推拿\n现在只要98元✨\n含肩颈+腰部+足部\n90分钟一次被揉足😌\n\n技师都是10年+老师傅\n手法稳、力道刚刚好\n\u4e0a班族、宝妈赶紧预约\n废才是赚到！',
        'hashtags': ['#周末便利', '#推拿特惠', '#养生', '#成都', '#平价好物', '#限时'],
        'image_prompt': 'A relaxing Chinese massage session, warm towels, dim spa lighting, peaceful atmosphere, top-down view, Xiaohongshu lifestyle photography',
        'images': ['https://images.unsplash.com/photo-1540555700478-4be289fbecef?w=800'],
    },
    {
        'topic': '上班族肩颈放松必看',
        'title': '💻上班族拯救指南 | 肩颈这样揉才有效',
        'body': '打字一天颅椎出问题的举手🙋‍♀️\n\n今天分享几个我亲测有用的点✨\n1、每周一次专业推拿\n2、办公桌放个貓貓抱枚\n3、晚上热敷足踝\n\n重点来了‼️\n找对推拿店太重要\n手法不专业越揉越痛\u3002\n评论区抢推荐👇',
        'hashtags': ['#上班族', '#肩颈疼痛', '#颅椎问题', '#养生日常', '#推拿', '#健康生活'],
        'image_prompt': 'A flat-lay of office worker neck care items: warm pack, massage roller, herbal tea cup, soft pastel colors, top-down lifestyle photo, Xiaohongshu style',
        'images': ['https://images.unsplash.com/photo-1559757148-5c350d0d3c56?w=800'],
    },
]


def seed():
    if not User.query.filter_by(email='admin@demo.com').first():
        admin = User(
            email='admin@demo.com',
            password_hash=bcrypt.hashpw(b'admin123', bcrypt.gensalt()),
            role='admin',
            verified=True,
        )
        admin.new_token()
        db.session.add(admin); db.session.commit()
        for d in DEMO_POSTS:
            p = Post(
                user_id=admin.id,
                topic=d['topic'], title=d['title'], body=d['body'],
                hashtags=json.dumps(d['hashtags'], ensure_ascii=False),
                image_prompt=d['image_prompt'],
                images=json.dumps(d['images'], ensure_ascii=False),
            )
            db.session.add(p)
        db.session.commit()
        print('Seeded admin@demo.com / admin123 + 3 demo posts')


with app.app_context():
    db.create_all()
    seed()


if __name__ == '__main__':
    import webbrowser, threading
    url = 'http://127.0.0.1:5000/'
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host='0.0.0.0', port=5000, debug=False)
