# Email Setup (Weekly Report)

The weekly Friday report can be sent by email via one of two paths:

1. **Resend** (HTTPS, recommended) — works from anywhere
2. **SMTP** — only if your host allows outbound SMTP (many PaaS don't)

## Path 1 — Resend (recommended)

Resend uses HTTPS on port 443, which bypasses the SMTP port blocks common on Railway, Heroku, Fly.io, and similar hosts.

### 1. Sign up at [resend.com](https://resend.com)

Free tier: 3,000 emails/month, 100/day. Plenty for a weekly team email.

### 2. Get an API key

Resend Dashboard → **API Keys** → **Create API Key** → give it "Sending access". Copy the key (`re_...`).

### 3. Verify a sending domain

You have two options:

**Option A — Verify your company domain** (e.g. `yourcompany.com`)

- Resend → **Domains** → **Add Domain** → `yourcompany.com`
- Add the DNS records Resend provides (SPF, DKIM, DMARC) to your DNS provider
- Wait ~15 minutes for propagation
- Now you can send from `anything@yourcompany.com`

**Option B — Use `onboarding@resend.dev`** (for testing only)

- No setup needed
- **Limitation:** you can only send to the email you signed up with

**Option C — Verify a subdomain** (less friction with IT)

- If your IT team doesn't want to touch the main domain's MX records
- Verify e.g. `mail.yourcompany.com` — only requires adding TXT/CNAME on a new subdomain

### 4. Configure env vars

```
RESEND_API_KEY=re_xxxxxxxxx
WEEKLY_REPORT_EMAIL_FROM=bot@yourcompany.com     # must be from verified domain
WEEKLY_REPORT_EMAIL_RECIPIENTS=alice@yourcompany.com,bob@yourcompany.com
WEEKLY_REPORT_EMAIL_ENABLED=true
```

### 5. Test

- Redeploy your app
- Log into the dashboard, open any report at `/reportes/<id>`
- Click **"Enviar prueba"**, enter your own email
- Should arrive in seconds

### 6. Verify the cron

Friday cron is registered on startup. Verify by checking bot logs on Friday, or by manually running the report generation from the dashboard on any day.

---

## Path 2 — SMTP

Only use this if your host allows outbound SMTP. Test with a simple `telnet smtp.gmail.com 587` from your production shell.

### Example: Gmail

Requires a Google account with 2-Step Verification enabled.

1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Generate an App Password for "Mail"
3. Set env vars:

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=<16-char app password, spaces optional>
SMTP_USE_TLS=true
SMTP_USE_SSL=false
WEEKLY_REPORT_EMAIL_FROM=you@gmail.com
WEEKLY_REPORT_EMAIL_RECIPIENTS=comma,separated,emails
```

### Example: Google Workspace with corporate domain

Same as above but `SMTP_USER=you@yourcompany.com` — this only works if your Workspace admin has enabled "Allow less secure apps" or the equivalent, and you've set up an app password.

### Example: Amazon SES

```
SMTP_HOST=email-smtp.us-east-1.amazonaws.com
SMTP_PORT=587
SMTP_USER=<SES SMTP username>
SMTP_PASSWORD=<SES SMTP password>
SMTP_USE_TLS=true
WEEKLY_REPORT_EMAIL_FROM=verified-sender@yourcompany.com
```

### Common SMTP failures

- **`Network is unreachable`** → Your host blocks SMTP. Switch to Resend.
- **`Timeout connecting to smtp.gmail.com:587`** → Same issue.
- **`Authentication failed`** → For Gmail, you're using your login password, not an App Password.
- **`550 relay not permitted`** → Sender is not authorized on the SMTP server; verify sender or use a different service.

---

## Disabling email entirely

If you want the weekly report generated in the dashboard but no email sent:

```
WEEKLY_REPORT_EMAIL_ENABLED=false
```

The Friday cron still generates and stores the report; only the email step is skipped.
