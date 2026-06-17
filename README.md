# 小红书文案 + AI 配图生成器

Flask + plain HTML/CSS/JS + SQLite. No React, no build step.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # only SECRET_KEY — do NOT put LLM keys here
python app.py
```

App opens automatically at http://127.0.0.1:5000/

## 🔑 Where to paste your API keys

**Not in `.env`. Not in code.** All LLM API keys are pasted into the UI:

1. Log in.
2. Go to **http://127.0.0.1:5000/settings** (top-right ⚙️ button).
3. Choose a provider and paste your key. Hit **Save**, then **🔌 Test Connection**.

Keys are encrypted (Fernet, derived from `SECRET_KEY`) and stored in SQLite, scoped to your user.

### Supported providers

| Type  | Providers |
|-------|-----------|
| Text  | OpenAI (gpt-4o-mini) · DeepSeek (deepseek-chat) · 通义 Qwen (qwen-plus / qwen-vl-plus) |
| Image | OpenAI DALL·E 3 · Stability AI (Stable Image Core) · 通义万相 (wanx-v1) |

Vision-based file parsing (image / PDF cover) requires OpenAI or Qwen.

## Demo login

```
email:    admin@demo.com
password: admin123
```

Admin can visit **/admin** to manage users, posts, and set **system fallback keys** that all users without their own key will use.

## Project layout

```
app.py              Flask backend, all routes, encryption, seeding
models.py           SQLAlchemy models: User, ApiKey, SystemKey, Post
mail_service.py     send_email() — prints + mail.log (TODO: real SMTP)
llm_service.py      Text LLM + vision parsing + image prompt builder
image_service.py    DALL·E / Stability / 通义万相 image generation
requirements.txt
.env.example        SECRET_KEY only
static/
  index.html        Main app (login / generate / preview)
  settings.html     API key management
  admin.html        Admin dashboard
  style.css         小红书 accent (#FF2442)
  app.js            Shared frontend logic
uploads/            Uploaded files
generated_images/   AI-generated images
database.db         Auto-created SQLite
```

## Critical security rules (already enforced)

- LLM API keys are **never** hardcoded.
- LLM API keys are **never** read from `.env`.
- `.env` only contains `SECRET_KEY` (and optional `FERNET_KEY`).
- User keys are encrypted at rest via Fernet.
- Passwords are bcrypt-hashed.
