# AGENTS.md — Installation & operation guide for AI coding assistants

> **Purpose:** hand this file to Cursor, Claude Code, GitHub Copilot Chat, or any other AI coding assistant. It contains the full, ordered instructions to set up, verify, customize, deploy, and troubleshoot Sales Coach Bot for a real company.
>
> **For humans:** you can absolutely read this too — it's just written in "checklist + exact command" style rather than prose.

> **⚠️ Before you start:** read [`DISCLAIMER.md`](DISCLAIMER.md). This software is provided "AS IS" with **no warranty and no liability** for security issues, data loss, third-party costs, LLM output accuracy, legal compliance, or HR consequences. You are solely responsible for your deployment, your data, your employees' consent, and your legal review.

---

## How this system works (one-page mental model)

Sales Coach Bot has **two long-running processes** and **one database**:

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│   Telegram user                                                  │
│        ▲                                                         │
│        │ 1. Bot sends 3-5 questions/day (APScheduler cron)       │
│        │ 2. Rep answers via text or voice                        │
│        ▼                                                         │
│   ┌─────────────┐        grades answer         ┌──────────────┐  │
│   │  bot.py     │───────────────────────────►  │  OpenAI /    │  │
│   │  (Telegram) │◄─────────── feedback ─────── │  Anthropic   │  │
│   └─────────────┘                              └──────────────┘  │
│        │                                                         │
│        ▼                                                         │
│   ┌──────────────────┐                                           │
│   │  SQLAlchemy DB   │  ◄─── read by ───┐                        │
│   │  (SQLite/PG)     │                  │                        │
│   └──────────────────┘                  │                        │
│        ▲                                │                        │
│        │                                │                        │
│   ┌─────────────┐                       │                        │
│   │ dashboard.py│  ── serves at :5000 ──┘                        │
│   │  (Flask)    │      manager UI, reports, leaderboards         │
│   └─────────────┘                                                │
│                                                                  │
│   Friday 10am CST: proactive_sender.py builds weekly report      │
│   Friday 11am CST: report_email.py sends HTML email via Resend   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Core loop each rep experiences:**
1. Bot sends question → 2. Rep answers → 3. LLM grades against knowledge base → 4. Points awarded, streak updated → 5. Feedback with "why it matters" shown → 6. If concept missed, adaptive probe follow-up → 7. Weekly report Friday.

**Key files by concern:**
- `config.py` — every environment variable, single source of truth
- `models/` — SQLAlchemy schema (users, questions, attempts, grades, sessions)
- `handlers/` — Telegram command + message handlers
- `services/grader.py` — LLM grading logic
- `services/proactive_sender.py` — APScheduler cron jobs (daily questions, reports, alerts)
- `services/report_email.py` — weekly HTML email builder (Resend or SMTP)
- `dashboard_app/routes.py` — all Flask routes
- `data/question_banks/*.json` — your questions
- `data/knowledge_bases/*.txt` — reference documents the grader uses

---

## Phase 0 — Prerequisites check

Run each command; expect the shown output. If any fails, install what's missing before continuing.

```bash
# 1. Python 3.9+
python3 --version
# expect: Python 3.9.x or higher

# 2. pip
python3 -m pip --version
# expect: pip 21.x or higher

# 3. git
git --version
# expect: git version 2.x
```

You'll also need accounts (free tiers are plenty):

- **Telegram account** — go to https://web.telegram.org, sign in
- **BotFather access** — message `@BotFather` on Telegram
- **OpenAI account** — create at https://platform.openai.com (~$5 free credit)
- **(Optional) Resend account** — for weekly email reports; https://resend.com

---

## Phase 1 — Clone and install

```bash
git clone https://github.com/santiagosbg01/sales-coach-bot.git
cd sales-coach-bot

python3 -m venv venv
source venv/bin/activate                # macOS/Linux
# venv\Scripts\activate                  # Windows PowerShell

pip install -r requirements.txt
```

**Verify:**
```bash
python -c "import telegram, flask, openai, sqlalchemy, apscheduler; print('All core deps import OK')"
# expect: All core deps import OK
```

---

## Phase 2 — Create the Telegram bot

**Steps in Telegram (manual — one-time):**

1. Open Telegram, search `@BotFather`, start chat
2. Send: `/newbot`
3. Choose a display name, e.g. `Acme Sales Coach`
4. Choose a username ending in `bot`, e.g. `acme_coach_bot`
5. **Copy the token** BotFather gives you (format: `1234567890:AAExxxxx...`)
6. Send `/setdescription` → describe your bot
7. Send `/setcommands` → paste this list:

```
start - Registrar tu cuenta y ver estado
preguntas - Recibir tus preguntas del día
extras - Preguntas adicionales cuando quieras más
ranking - Ver leaderboard del equipo
puntos - Ver tus puntos y racha
premios - Ver premios canjeables
help - Ayuda y comandos disponibles
```

---

## Phase 3 — Get your OpenAI key

1. Go to https://platform.openai.com/api-keys
2. Click **Create new secret key**, name it "sales-coach-bot"
3. Copy the key (starts with `sk-...`) — **you won't see it again**

---

## Phase 4 — Configure `.env`

```bash
cp .env.example .env
```

Now edit `.env`. **Minimum required for a first successful run:**

```env
# Branding — how your bot introduces itself
APP_NAME=Acme Sales Coach
COMPANY_NAME=Acme Corp

# Telegram — from BotFather
TELEGRAM_BOT_TOKEN=1234567890:AAExxxxx...

# OpenAI — for LLM grading
OPENAI_API_KEY=sk-xxxxx...

# Flask — session security & admin login
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
ADMIN_PASSWORD=<pick a strong password>

# Database — SQLite for dev, Postgres for prod
DATABASE_URL=sqlite:///sales_coach.db

# Your product taxonomy (comma-separated)
VALID_SERVICES=product_a,general

# Countries you operate in
COUNTRIES=all,mexico,colombia,chile,peru
```

Leave everything else at defaults for now.

---

## Phase 5 — Initialize the database

```bash
python scripts/init_db.py
```

**Verify:**
```bash
ls -la sales_coach.db
# expect: a file exists

python -c "from models import SessionLocal, User; db = SessionLocal(); print(f'Users in DB: {db.query(User).count()}'); db.close()"
# expect: Users in DB: 0
```

---

## Phase 6 — Load sample questions

Start with the SaaS example bank (12 questions, all categories):

```bash
python scripts/load_questions.py data/question_banks/saas_example.json
```

**Verify:**
```bash
python -c "from models import SessionLocal, Question; db = SessionLocal(); print(f'Questions in DB: {db.query(Question).count()}'); db.close()"
# expect: Questions in DB: 12
```

You can also load the other example banks:

```bash
python scripts/load_questions.py data/question_banks/ecommerce_example.json
python scripts/load_questions.py data/question_banks/services_example.json
```

---

## Phase 7 — Register yourself as admin

You need your Telegram chat ID first. Two ways:

**Method A (recommended) — via the bot:**

```bash
# Start the bot briefly to see incoming updates:
python bot.py
```

- In Telegram, message your bot: `/start`
- Look at the terminal — you'll see something like: `Update from chat_id: 6936XXXXXX`
- Copy that number
- Stop the bot with Ctrl+C

**Method B — via @userinfobot:**
- Message `@userinfobot` on Telegram, it replies with your ID

**Now register yourself as admin:**

```bash
python scripts/create_admin.py "Your Full Name" you@example.com 6936XXXXXX
```

Replace `6936XXXXXX` with your actual chat ID. Also add it to `.env`:

```env
ADMIN_CHAT_ID=6936XXXXXX
MANAGER_ALERT_CHAT_IDS=6936XXXXXX
```

---

## Phase 8 — Run bot + dashboard

You need **two terminals** (or use `foreman start` if you set up a Procfile).

**Terminal A — the Telegram bot:**
```bash
source venv/bin/activate
python bot.py
# expect: "Bot started, polling..." (or similar)
```

**Terminal B — the web dashboard:**
```bash
source venv/bin/activate
python dashboard.py
# expect: "Running on http://0.0.0.0:5000"
```

---

## Phase 9 — Test end-to-end

**On the dashboard:**
1. Open http://localhost:5000
2. Log in with the `ADMIN_PASSWORD` from your `.env`
3. Navigate to **Users** — you should see yourself listed as admin
4. Navigate to **Questions** — you should see 12 (or more) questions

**On Telegram, send to your bot:**

```
/start
# expect: welcome message with your name

/preguntas
# expect: receive your first question with 4 answer choices (multiple choice) or a text prompt

# Answer the question. If it's open-ended, type an answer.
# Expect: within 3-5 seconds, feedback appears with:
#   - Grade (✅ or ⚠️ or ❌)
#   - Why-it-matters explanation
#   - Points awarded
#   - Weekly accuracy trend

/puntos
# expect: your points, streak, and rank

/ranking
# expect: leaderboard (just you for now)
```

**Back on the dashboard:**
- Refresh → you should see your attempt logged
- Navigate to **Reportes** → click **Generar** to create your first weekly snapshot

If all above works: **the system is fully operational.**

---

## Phase 10 — Adapt to your company (the 3 real customization axes)

### 10a. Write your own question bank

```bash
cp data/question_banks/saas_example.json data/question_banks/mycompany.json
$EDITOR data/question_banks/mycompany.json
```

Follow the schema in [`docs/QUESTION_BANK_FORMAT.md`](docs/QUESTION_BANK_FORMAT.md). Aim for **at least 20-30 questions per category** (discovery, objections, qualification, closing, value_proposition) so reps don't see repeats.

Load it:
```bash
python scripts/load_questions.py data/question_banks/mycompany.json
```

### 10b. Add your product's knowledge base

Save your product FAQ, playbook, or one-pager as plain text:

```bash
$EDITOR data/knowledge_bases/mycompany_product.txt
```

Then use `mycompany_product` as the `product` tag on relevant questions. The grader will inject this text as ground truth.

Keep each file under **8 KB** for best LLM performance.

### 10c. Update env vars for your taxonomy

```env
VALID_SERVICES=mycompany_product,onboarding,implementation,general
COUNTRIES=all,usa,uk,mexico,brazil
```

Restart both processes (`bot.py` and `dashboard.py`) after editing `.env`.

---

## Phase 11 — Onboard your team

For each rep, use the dashboard or the CLI:

**Via dashboard:**
- Navigate to **Users** → **Enroll rep** → fill in name, email, country, specializations

**Via CLI:**
```bash
python scripts/enroll_user.py "Rep Name" rep@company.com <their_telegram_chat_id>
```

Each rep needs to have already messaged your bot with `/start` so it has their chat_id. You can send them a shared enrollment link:

```
https://t.me/<your_bot_username>?start=enroll
```

Configure the enrollment gate in `.env` if you want to restrict by email domain:

```env
ENROLL_EMAIL_DOMAIN=yourcompany.com
ENROLL_CODE=welcome2025
```

---

## Phase 12 — Enable the weekly report email

The Friday cron generates a report at 10 AM CST and emails it at 11 AM CST. Follow [`docs/EMAIL_SETUP.md`](docs/EMAIL_SETUP.md), but the short version with Resend:

1. Sign up at https://resend.com (free 3,000 emails/month)
2. Verify a domain (or use `onboarding@resend.dev` for testing to yourself only)
3. Create an API key
4. Add to `.env`:

```env
RESEND_API_KEY=re_xxxxx
WEEKLY_REPORT_EMAIL_FROM=bot@yourcompany.com
WEEKLY_REPORT_EMAIL_RECIPIENTS=manager1@yourcompany.com,manager2@yourcompany.com
WEEKLY_REPORT_EMAIL_ENABLED=true
```

**Test immediately (don't wait until Friday):**
- Open http://localhost:5000/reportes
- Click **Generar** to create a fresh snapshot
- Open the report → click **Enviar prueba** → enter your email
- Should arrive in seconds

---

## Phase 13 — Deploy to production

Pick one path (see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for detail):

### Path A — Railway (simplest, recommended)

1. Push your (private) fork to GitHub
2. Go to https://railway.app → New Project → Deploy from GitHub
3. Add a **PostgreSQL** service in the same project
4. Copy all `.env` values to Railway → Variables (except `DATABASE_URL`, which Railway injects)
5. Set `ENV=production`, `DEBUG=false`
6. Split into two services: one running `python bot.py`, one running `python dashboard.py`
7. Set the dashboard service's start command in Railway UI; use the provided public URL as your `BASE_URL`

**Important:** Railway blocks outbound SMTP on all ports. **Use Resend**, not SMTP.

### Path B — VPS with systemd

```bash
ssh your-server
git clone https://github.com/santiagosbg01/sales-coach-bot.git
cd sales-coach-bot
bash deploy/setup_server.sh
$EDITOR ~/sales-coach-bot/.env    # fill in real values
sudo systemctl restart sales-coach-bot sales-coach-dashboard
```

Set up Nginx + Let's Encrypt to serve the dashboard on your domain.

---

## Phase 14 — Verify production is healthy

```bash
# From your laptop, hit the dashboard health endpoint
curl -I https://your-domain/health
# expect: HTTP/1.1 200 OK

# Send /start to your bot from Telegram
# expect: response within 2 seconds

# In the dashboard, check the Reportes page — the Friday cron should be registered
```

Check bot logs on Friday around your cron time to confirm the scheduled report was generated and email was sent.

---

## Troubleshooting cheat-sheet

| Symptom | Diagnosis | Fix |
|---|---|---|
| Bot doesn't respond to `/start` | Wrong `TELEGRAM_BOT_TOKEN` or two bot processes running | Verify token; kill all `python bot.py` processes |
| "OPENAI_API_KEY not set" | `.env` missing or not loaded | `ls -la .env` — must be in repo root; restart process |
| `AttributeError: type object 'Attempt' has no attribute '...'` | Model schema drift | Run `python scripts/init_db.py` (dev only — prod needs migration) |
| Dashboard 500 on `/reportes/*/email` | `WEEKLY_REPORT_EMAIL_FROM` empty | Set it in `.env` |
| SMTP timeout on Railway/Heroku/Fly | Provider blocks SMTP egress | Switch to Resend via `RESEND_API_KEY` |
| Resend 403 "You can only send to your own email" | Domain not verified in Resend | Verify a domain or subdomain in Resend dashboard |
| Reps see the same question repeatedly | Too few active questions in DB | Load more question banks (see Phase 10a) |
| "coach reports 0 attempts" but reps answered | `answered_at` filter mismatch | Verify with `python scripts/check_db.py` |
| Weekly cron didn't run on Friday | `bot.py` crashed or was restarted at cron time | Deploy with a process supervisor (Railway/systemd) |

---

## Common maintenance tasks

### Add more questions to an existing bank
Edit the JSON and re-run `python scripts/load_questions.py <file>` — new questions are added. Use `--replace` to overwrite the whole bank.

### Rotate the OpenAI key
Edit `OPENAI_API_KEY` in `.env` or Railway env vars, restart both processes. No DB change needed.

### Reset a rep's streak
```bash
python -c "
from models import SessionLocal, User
db = SessionLocal()
u = db.query(User).filter_by(email='rep@company.com').first()
u.current_streak = 0
db.commit()
"
```

### Export weekly report data as CSV
On the dashboard, `/reportes/<id>` → **Export CSV** button.

### Debug what a rep received today
```bash
python scripts/check_db.py --rep rep@company.com --today
```

---

## What to hand to your AI assistant when things break

When something misbehaves and you want an AI to help debug:

1. **Copy this file** (`AGENTS.md`) into the conversation for context
2. **Paste the relevant log** from Terminal A (`bot.py`) or Terminal B (`dashboard.py`) — 20-30 lines around the error
3. **Include your `.env` variable names** (values redacted) so the AI knows what's configured
4. **State the last thing that worked** and the change you made right before it broke

The AI will have full context to help without guessing.

---

## Where to go next

- [`README.md`](README.md) — high-level pitch and feature list
- [`docs/SETUP.md`](docs/SETUP.md) — human-oriented setup (essentially Phases 0-9 in prose)
- [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) — every env var explained
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — Railway, VPS, Fly.io deep dives
- [`docs/CUSTOMIZATION.md`](docs/CUSTOMIZATION.md) — branding, cadence, scoring
- [`docs/QUESTION_BANK_FORMAT.md`](docs/QUESTION_BANK_FORMAT.md) — JSON schema
- [`docs/EMAIL_SETUP.md`](docs/EMAIL_SETUP.md) — Resend + SMTP config
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to contribute back
