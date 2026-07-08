#!/bin/bash
# =============================================================================
# Sales Coach — Server Setup Script
# Run this once on a fresh EC2 instance.
# Usage: bash setup_server.sh
# =============================================================================

set -e  # Exit on any error

PROJECT_DIR="$HOME/sales-coach-bot"
VENV_DIR="$PROJECT_DIR/venv"
SERVICE_USER=$(whoami)

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   Sales Coach — Server Setup        ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. System packages ────────────────────────────────────────────────────────
echo "📦 Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y -q python3-pip python3-venv git screen

# ── 2. Clone or pull repo ─────────────────────────────────────────────────────
if [ -d "$PROJECT_DIR" ]; then
  echo "📥 Pulling latest code..."
  cd "$PROJECT_DIR"
  git pull
else
  echo ""
  echo "📥 Enter your GitHub repo URL (e.g. https://github.com/youruser/sales-coach-bot.git):"
  read -r REPO_URL
  git clone "$REPO_URL" "$PROJECT_DIR"
  cd "$PROJECT_DIR"
fi

# ── 3. Python virtual environment ─────────────────────────────────────────────
echo "🐍 Setting up Python virtual environment..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r requirements.txt -q
echo "✅ Dependencies installed"

# ── 4. Environment file ───────────────────────────────────────────────────────
if [ ! -f "$PROJECT_DIR/.env" ]; then
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
  echo ""
  echo "⚠️  .env file created from template."
  echo "    Edit it now: nano $PROJECT_DIR/.env"
  echo "    Then re-run this script."
  echo ""
  echo "    Required values:"
  echo "      TELEGRAM_BOT_TOKEN=..."
  echo "      ANTHROPIC_API_KEY=..."
  echo "      SECRET_KEY=\$(python3 -c \"import secrets; print(secrets.token_hex(32))\")"
  exit 0
fi

# ── 5. Database & questions ───────────────────────────────────────────────────
echo "🗄️  Initializing database..."
cd "$PROJECT_DIR"
"$VENV_DIR/bin/python" -c "from models import init_db; init_db()" 2>/dev/null

echo "📚 Loading question banks..."
for f in data/*.json; do
  echo "   Loading: $f"
  "$VENV_DIR/bin/python" scripts/load_questions.py "$f" 2>/dev/null | grep -E "✅|⚠️|📦"
done

# ── 6. systemd services ───────────────────────────────────────────────────────
echo "⚙️  Installing systemd services..."

# Bot service
sudo tee /etc/systemd/system/sales-coach-bot.service > /dev/null <<EOF
[Unit]
Description=Sales Coach — Telegram Bot
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV_DIR/bin/python bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Dashboard service (optional but included)
sudo tee /etc/systemd/system/sales-coach-dashboard.service > /dev/null <<EOF
[Unit]
Description=Sales Coach — Manager Dashboard
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV_DIR/bin/python dashboard.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable sales-coach-bot
sudo systemctl enable sales-coach-dashboard
sudo systemctl start sales-coach-bot
sudo systemctl start sales-coach-dashboard

# ── 7. Status check ───────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   ✅ Setup Complete!                     ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "🤖 Bot status:"
sudo systemctl status sales-coach-bot --no-pager -l | tail -5
echo ""
echo "📊 Dashboard status:"
sudo systemctl status sales-coach-dashboard --no-pager -l | tail -5
echo ""
echo "📋 Useful commands:"
echo "   View bot logs:       sudo journalctl -u sales-coach-bot -f"
echo "   View dashboard logs: sudo journalctl -u sales-coach-dashboard -f"
echo "   Restart bot:         sudo systemctl restart sales-coach-bot"
echo "   Stop bot:            sudo systemctl stop sales-coach-bot"
echo ""
echo "🌐 Dashboard: http://$(curl -s ifconfig.me 2>/dev/null || echo YOUR_EC2_IP):5000"
echo ""
