# Deployment

This project runs anywhere Python 3.9+ runs. Two options in detail below: **Railway** (easiest, recommended) and a **VPS** via systemd.

---

## Option A — Railway (recommended)

Railway auto-detects Python, gives you free PostgreSQL, and handles process supervision. Free tier is enough for a small team.

### 1. Push your fork to GitHub

```bash
git remote add origin https://github.com/YOUR_USERNAME/sales-coach-bot.git
git push -u origin main
```

### 2. Create a Railway project

- Go to [railway.app](https://railway.app), create a new project from your GitHub repo
- Add a **Postgres** service (New → Database → PostgreSQL)
- Railway will inject `DATABASE_URL` automatically into your app service

### 3. Set environment variables

In the Railway UI, under your app service → Variables, paste:

```
APP_NAME=Your Coach
COMPANY_NAME=Your Company
TELEGRAM_BOT_TOKEN=...
OPENAI_API_KEY=...
SECRET_KEY=<random>
ADMIN_PASSWORD=<strong>
ADMIN_CHAT_ID=<your telegram chat id>
VALID_SERVICES=product_a,general
RESEND_API_KEY=<optional, for weekly email>
WEEKLY_REPORT_EMAIL_FROM=<your verified Resend sender>
WEEKLY_REPORT_EMAIL_RECIPIENTS=<comma-separated>
ENV=production
DEBUG=false
```

### 4. Configure two processes

Railway reads `Procfile`. The included one runs the dashboard. If you want the bot in the same service:

```
web: python dashboard.py
worker: python bot.py
```

Or split them into two Railway services pointing at the same repo (recommended). Each service has its own start command.

### 5. Deploy

Push to `main` — Railway auto-deploys.

### 6. Verify

- Visit the public URL Railway gave you → dashboard login screen
- Message your bot on Telegram → `/start` should work

---

## Option B — VPS with systemd

For full control (DigitalOcean, Hetzner, EC2, etc.). Uses the scripts in `deploy/`.

### 1. Set up a Ubuntu/Debian server

Minimum: 1 vCPU, 1 GB RAM, 10 GB disk. Install Python 3.9+ and PostgreSQL (or use SQLite for very small deployments).

### 2. Clone and run the setup script

```bash
ssh your-server
git clone https://github.com/YOUR_USERNAME/sales-coach-bot.git
cd sales-coach-bot
bash deploy/setup_server.sh
```

The script:
- Creates a Python venv
- Installs dependencies
- Copies `.env.example` → `.env` (you edit it)
- Creates two systemd services (`sales-coach-bot`, `sales-coach-dashboard`)
- Starts them

### 3. Edit your env

```bash
nano ~/sales-coach-bot/.env
```

Fill in the same variables as the Railway example.

### 4. Restart services

```bash
sudo systemctl restart sales-coach-bot
sudo systemctl restart sales-coach-dashboard
```

### 5. Set up a reverse proxy for the dashboard

Install Nginx and point port 80/443 to `localhost:5000`. Use Let's Encrypt for HTTPS:

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo certbot --nginx -d coach.yourdomain.com
```

---

## Option C — Fly.io / Render / other

Any host that supports long-running Python processes works. Just ensure:

- Both `bot.py` (long-running) and `dashboard.py` (web) are running
- Same database connection for both processes
- Environment variables set
- Persistent volume if using SQLite; otherwise Postgres

---

## Post-deploy checklist

- [ ] `/health` endpoint returns 200 (dashboard is up)
- [ ] Bot responds to `/start` on Telegram
- [ ] You can log into the dashboard at `<your-url>/login`
- [ ] Send yourself a test question via `/preguntas`
- [ ] Answer it, check that the grade posts to the dashboard
- [ ] Try `/reportes` → "Enviar prueba" to yourself
- [ ] Confirm the Friday scheduler is registered (check bot logs on startup)

## Troubleshooting

- **Bot ignores messages** — check `TELEGRAM_BOT_TOKEN` is right. Only ONE bot process can poll at a time; if you have two running, one silently loses.
- **"Network is unreachable" for SMTP** — Railway blocks all SMTP ports. Switch to Resend.
- **Dashboard errors on `/reportes`** — likely `WEEKLY_REPORT_EMAIL_FROM` empty. Set it.
- **Weekly cron didn't fire** — bot must be running on Friday at the scheduled time. If bot restarts often, use Railway's cron primitive instead.
