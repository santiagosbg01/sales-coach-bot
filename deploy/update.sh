#!/bin/bash
# =============================================================================
# Sales Coach — Update Script
# Run this every time you push new code to GitHub.
# Usage: bash deploy/update.sh
# =============================================================================

set -e

PROJECT_DIR="$HOME/sales-coach-bot"
VENV_DIR="$PROJECT_DIR/venv"

echo ""
echo "🔄 Updating Sales Coach..."

cd "$PROJECT_DIR"

# Pull latest code
git pull

# Install any new dependencies
"$VENV_DIR/bin/pip" install -r requirements.txt -q

# Load any new question bank files
for f in data/*.json; do
  "$VENV_DIR/bin/python" scripts/load_questions.py "$f" 2>/dev/null | grep -E "✅|📦|Cargadas"
done

# Restart services
sudo systemctl restart sales-coach-bot
sudo systemctl restart sales-coach-dashboard

echo ""
echo "✅ Update complete!"
echo ""
sudo systemctl status sales-coach-bot --no-pager -l | tail -4
