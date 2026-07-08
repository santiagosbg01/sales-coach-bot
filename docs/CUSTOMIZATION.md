# Customization Guide

Six things you'll want to adapt to your company. Ordered by frequency of change.

---

## 1. Question banks

Your #1 lever. Adapt the sample banks or write new ones:

```bash
# Copy an example as your starting point
cp data/question_banks/saas_example.json data/question_banks/mycompany.json

# Edit prompts, choices, rubrics, tags to reflect your product/methodology
$EDITOR data/question_banks/mycompany.json

# Load it
python scripts/load_questions.py data/question_banks/mycompany.json
```

See [`QUESTION_BANK_FORMAT.md`](QUESTION_BANK_FORMAT.md) for schema details.

**Rule of thumb:** aim for at least 20-30 active questions per category (discovery, objections, qualification, closing, value_proposition). With less than that, reps see repeats too often.

---

## 2. Knowledge bases

Drop plain-text product docs in `data/knowledge_bases/`. Filename must match the `product` tag on your questions.

```
data/knowledge_bases/
├── general.txt         # Fallback for any untagged question
├── crm.txt             # Loaded when question.product == "crm"
├── onboarding.txt      # Loaded when question.product == "onboarding"
└── ...
```

Keep each file under 8 KB. Focus on facts, differentiators, common objections, case study snippets. The LLM sees this as ground truth during grading.

---

## 3. Branding

Change how the bot introduces itself:

```
# .env
APP_NAME="Acme Sales Coach"
COMPANY_NAME="Acme Corp"
```

These strings appear in:
- Bot welcome messages
- Dashboard header and page titles
- Email report headers
- LLM grader system prompt

---

## 4. Product/service tags & countries

```
# .env
VALID_SERVICES=crm,onboarding,implementation,general
COUNTRIES=all,usa,uk,brazil,mexico
```

Restart the app for changes to take effect.

---

## 5. Cadence & difficulty

Tune how many questions reps get per day, how aggressively the bot probes, and how spaced repetition works:

```
DAILY_QUESTIONS_COUNT=5           # Base per day
DAILY_QUESTIONS_MAX=10            # Cap with extras
MAX_PROBES_PER_QUESTION=3         # LLM follow-ups on missed concepts
ANTI_REPEAT_DAYS=7                # Don't repeat within N days
REMINDER_HOURS=4                  # Nudge time
SR_REVIEW_INTERVALS=3,7,14        # Spaced repetition days
```

---

## 6. Grading behavior

The grader's LLM prompt is in `services/grader.py`. Look for the `system_msg` string near the top of `_llm_score`. You can:

- Change the persona/tone
- Add company-specific grading rules (e.g. "always mark answers that mention our USP as at least a 3")
- Enable/disable framework evaluation via env:
  ```
  ENABLE_SPIN_EVALUATION=true
  ENABLE_CHALLENGER_EVALUATION=true
  SHOW_BONUS_SCORES_TO_REPS=false
  ```

---

## Advanced: extend the schema

If you want new metrics, new question types, or a new dimension (e.g. per-account leaderboards):

1. Add fields to the relevant model in `models/`
2. Run `python scripts/init_db.py` to regenerate the schema locally (dev only — for prod, write a proper Alembic migration)
3. Update `services/team_performance_report.py` to compute the new metric
4. Add a column to the relevant dashboard template

Keep the "shell" spirit: don't hardcode your company's concepts into shared code. Use env vars and config, not `if company == "MyCorp"` branches.
