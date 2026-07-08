# Contributing

Contributions are welcome. This project is intentionally kept small and adaptable — the goal is a shell that companies fork, not a monolithic platform. Please keep changes focused on that principle.

## Ways to contribute

- **Bug fixes** — anything broken, especially in scheduling, grading, or the dashboard
- **New integrations** — WhatsApp, Slack, Microsoft Teams as alternative delivery channels
- **Better grading prompts** — improvements to the LLM system prompts in `services/grader.py`
- **New question types** — extensions to `question.py` and grader (e.g. audio-only, image-based)
- **Additional languages** — the current bot text is in Spanish; PRs for English/Portuguese/French welcome
- **Documentation** — clearer setup guides, more customization examples

## Ground rules

1. **No PII in commits.** Do not include real emails, chat IDs, API keys, or internal company data in code or tests. Use placeholders like `you@example.com` or `123456789`.
2. **No hardcoded company/product names.** Everything company-specific must be configurable via env vars or database. If you find a leftover reference, that's a bug worth fixing.
3. **Small, focused PRs.** One feature or fix per PR. Long threads get abandoned.
4. **Tests when reasonable.** If you're changing grading logic, scheduling, or scoring, please add or update tests.
5. **Match the code style.** Spanish for user-facing text, English for code/comments. Type hints on new functions.

## Development setup

```bash
git clone https://github.com/YOUR_USERNAME/sales-coach-bot.git
cd sales-coach-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN and OPENAI_API_KEY (use test/dev keys)
python scripts/init_db.py
python scripts/load_questions.py data/question_banks/saas_example.json
```

Run tests (if you add them):

```bash
pytest tests/
```

## Reporting bugs

Open an issue with:

- What you were trying to do
- What you expected to happen
- What actually happened
- Steps to reproduce (env vars redacted, please)
- Python version and OS

## Feature requests

Open a discussion (not an issue) first, so we can talk about fit and scope before you build. The bar is: does this make the shell more useful for many companies, or is it specific to yours? Specific things belong in your fork; general things can come here.

## Code of conduct

Be respectful. Assume good intent. Focus on the work.
