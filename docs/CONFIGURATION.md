# Configuration Reference

Every environment variable, grouped by concern. Set these in `.env` locally or in your hosting provider's dashboard in production.

## Required

| Variable | Description | Example |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Token from @BotFather | `1234567:ABC-...` |
| `OPENAI_API_KEY` | OpenAI API key for grading | `sk-...` |
| `SECRET_KEY` | Any random string to sign Flask sessions | `openssl rand -hex 32` output |
| `ADMIN_PASSWORD` | Login password for `/login` | (pick a strong one) |

## Branding

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `"Sales Coach"` | Shown in bot messages, dashboard header, email subjects |
| `COMPANY_NAME` | `"Your Company"` | Used in LLM grader system prompt and email footer |

## Database

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///sales_coach.db` | Use `postgresql://...` in production |

## Product/service segmentation

| Variable | Default | Notes |
|---|---|---|
| `VALID_SERVICES` | `product_a,product_b,product_c,general` | Comma-separated. Every product tag on your questions must appear here. |
| `COUNTRIES` | `all,mexico,colombia,chile,peru` | Rep base countries. Add your own. |

## Admin & alerts

| Variable | Purpose |
|---|---|
| `ADMIN_CHAT_ID` | Telegram chat ID(s) allowed to use `/resumen`, `/yesterday`, etc. |
| `MANAGER_ALERT_CHAT_IDS` | Same as above; comma-separated for multiple admins |
| `INACTIVITY_ALERT_DAYS` | Days without answering before alerting rep + manager (default 3) |

## Bot behavior

| Variable | Default | Notes |
|---|---|---|
| `DAILY_QUESTIONS_COUNT` | `5` | Base questions per day |
| `DAILY_QUESTIONS_MAX` | `10` | Cap including extra requested by rep |
| `MAX_PROBES_PER_QUESTION` | `3` | LLM follow-ups on missed concepts |
| `ANTI_REPEAT_DAYS` | `7` | Don't repeat a question sent in last N days |
| `REMINDER_HOURS` | `4` | Hours before nudging rep to answer |
| `SR_REVIEW_INTERVALS` | `3,7,14` | Days between spaced-repetition reviews |
| `SR_MAX_REVIEWS_PER_DAY` | `2` | Max spaced-repetition items per day |

## Enrollment (self-service)

| Variable | Purpose |
|---|---|
| `ENROLL_EMAIL_DOMAIN` | Restrict enrollment to `@<domain>` addresses. Leave empty to allow any. |
| `ENROLL_CODE` | Shared code used in the enrollment URL |

## Weekly email report

Preferred path is **Resend** (HTTPS on port 443, avoids SMTP block issues on Railway/Heroku/Fly).

| Variable | Purpose |
|---|---|
| `RESEND_API_KEY` | API key from resend.com |
| `WEEKLY_REPORT_EMAIL_FROM` | Verified sender address in Resend |
| `WEEKLY_REPORT_EMAIL_RECIPIENTS` | Comma-separated recipient emails |
| `WEEKLY_REPORT_EMAIL_ENABLED` | `true`/`false` — set to `false` to disable |

SMTP fallback (only if your host allows SMTP egress):

| Variable | Notes |
|---|---|
| `SMTP_HOST` | e.g. `smtp.gmail.com` |
| `SMTP_PORT` | `587` (STARTTLS) or `465` (SSL) |
| `SMTP_USER` | Full email address |
| `SMTP_PASSWORD` | App password for Gmail; not your login password |
| `SMTP_USE_TLS` | `true` for port 587 |
| `SMTP_USE_SSL` | `true` for port 465 |
| `SMTP_TIMEOUT` | Seconds before timing out (default 25) |

## Scoring

| Variable | Default | Purpose |
|---|---|---|
| `ENABLE_SPIN_EVALUATION` | `true` | Additional SPIN framework scoring |
| `ENABLE_CHALLENGER_EVALUATION` | `true` | Challenger sale framework scoring |
| `SHOW_BONUS_SCORES_TO_REPS` | `false` | Show framework scores in rep messages |
| `ENABLE_DIFFICULTY_PROGRESSION` | `false` | Adapt difficulty per rep skill (disabled by default so leaderboard is comparable) |
| `DIFFICULTY_LOOKBACK_DAYS` | `14` | Window for difficulty progression calculation |

## Runtime

| Variable | Default |
|---|---|
| `ENV` | `development` |
| `DEBUG` | `true` |
| `DASHBOARD_HOST` | `0.0.0.0` |
| `DASHBOARD_PORT` | `5000` |
| `BASE_URL` | (auto-detected on Railway; set manually otherwise) |
