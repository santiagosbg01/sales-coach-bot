# Local Development Setup

This walks you through running Sales Coach Bot on your laptop for the first time.

## Prerequisites

- **Python 3.9+** (`python3 --version` to check)
- **pip** (comes with Python)
- **A Telegram account** and access to `@BotFather` to create a bot
- **An OpenAI account** with API access (~$5 free credit works for months of testing)

## Step 1 — Clone and install dependencies

```bash
git clone https://github.com/YOUR_USERNAME/sales-coach-bot.git
cd sales-coach-bot

python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Step 2 — Create your Telegram bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot`
3. Choose a display name (e.g. "Acme Sales Coach")
4. Choose a username ending in `bot` (e.g. `acme_coach_bot`)
5. Copy the token BotFather gives you (looks like `1234567:ABC-DEF...`)

## Step 3 — Get an OpenAI API key

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Create a new secret key
3. Copy it (starts with `sk-...`)

## Step 4 — Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in at minimum:

```
APP_NAME="Acme Sales Coach"
COMPANY_NAME="Acme Corp"
TELEGRAM_BOT_TOKEN=1234567:ABC-DEF...
OPENAI_API_KEY=sk-...
SECRET_KEY=any-random-string-you-invent
ADMIN_PASSWORD=pick-a-strong-one
VALID_SERVICES=product_a,general
```

## Step 5 — Initialize the database

```bash
python scripts/init_db.py
```

This creates a SQLite file (`sales_coach.db`) with all tables.

## Step 6 — Load a sample question bank

```bash
python scripts/load_questions.py data/question_banks/saas_example.json
```

You should see: `Loaded 12 questions from saas_example`.

## Step 7 — Create yourself as admin

First, find your Telegram chat ID:

1. Message your bot (any text) to establish a chat
2. In another terminal, run `python bot.py` briefly, then check the console for a line like `Update from chat_id: 6936XXXXXX`
3. Stop the bot (Ctrl+C) and use that ID:

```bash
python scripts/create_admin.py "Your Name" you@example.com 6936XXXXXX
```

## Step 8 — Run the bot and dashboard

You need two terminals:

**Terminal A — bot:**
```bash
source venv/bin/activate
python bot.py
```

**Terminal B — dashboard:**
```bash
source venv/bin/activate
python dashboard.py
```

## Step 9 — Test end-to-end

- Open [http://localhost:5000](http://localhost:5000), log in with your `ADMIN_PASSWORD`
- On Telegram, message your bot with `/start`
- Then send `/preguntas` — you should receive your first question
- Answer it, get graded, see your points update

## Common issues

- **Bot doesn't respond** → Check the terminal running `bot.py`. Errors show there.
- **"OPENAI_API_KEY not set"** → Confirm `.env` is in the project root and `python-dotenv` loaded it (no manual sourcing needed).
- **"Sin proveedor de email"** on dashboard reports → Email is optional; ignore unless you want the weekly report to actually send.
- **Dashboard shows no data** → You haven't answered any questions yet. Send yourself a few via Telegram first.

## Next

- [`CONFIGURATION.md`](CONFIGURATION.md) — Every env var explained
- [`QUESTION_BANK_FORMAT.md`](QUESTION_BANK_FORMAT.md) — Write your own questions
- [`DEPLOYMENT.md`](DEPLOYMENT.md) — Ship it to production
