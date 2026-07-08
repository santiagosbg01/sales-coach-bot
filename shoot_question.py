"""
Standalone question shooter — runs via GitHub Actions cron.

Key behaviours:
  • Each enrolled user receives a DIFFERENT question per run.
  • No question is repeated to the same user within the same day.
  • Each user's message is sent after a random delay (0–9 min) so that
    reps can't compare timestamps and infer they got the same prompt.
  • State is stored per-user in data/.sent_today.json and cached by
    GitHub Actions between cron runs on the same day.
"""
import json
import os
import random
import hashlib
import time
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DATA_DIR = Path(__file__).parent / "data"
USERS_FILE = DATA_DIR / "enrolled_users.json"
STATE_FILE = DATA_DIR / ".sent_today.json"

# Maximum random delay in seconds added before sending to each user.
# With 9 min spread the whole run finishes well inside 15 min.
MAX_DELAY_SECONDS = 540  # 9 minutes


# ── Data loading ─────────────────────────────────────────────────────────────

def load_all_questions() -> list[dict]:
    questions = []
    for f in DATA_DIR.glob("*.json"):
        if f.name in ("enrolled_users.json", ".sent_today.json"):
            continue
        with open(f, encoding="utf-8") as fh:
            bank = json.load(fh)
        bank_name = bank.get("bank_name", f.stem)
        for q in bank.get("questions", []):
            q["_bank"] = bank_name
        questions.extend(bank.get("questions", []))
    return questions


def load_enrolled_users() -> list[dict]:
    if not USERS_FILE.exists():
        print("⚠️  No enrolled_users.json found")
        return []
    with open(USERS_FILE, encoding="utf-8") as fh:
        return json.load(fh).get("users", [])


def load_state() -> dict:
    """
    Returns {
      "date": "YYYY-MM-DD",
      "per_user": { "<chat_id>": ["qid1", "qid2", ...], ... }
    }
    Resets automatically when the date changes.
    """
    today = str(date.today())
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("date") == today:
            return data
    return {"date": today, "per_user": {}}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


# ── Question selection ────────────────────────────────────────────────────────

def question_id(q: dict) -> str:
    raw = f"{q.get('_bank', '')}__{q.get('prompt', '')}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def pick_for_user(
    questions: list[dict],
    user_sent_today: list[str],
    already_picked_this_run: set[str],
):
    """
    Pick a question that:
      1. The user hasn't received today.
      2. No other user has been assigned in this same run (anti-copy).
    Falls back to only rule 1 if the question pool is small,
    and to any question if the user has seen all questions today.
    """
    # Priority 1: unseen today AND not picked by another user this run
    pool = [
        q for q in questions
        if question_id(q) not in user_sent_today
        and question_id(q) not in already_picked_this_run
    ]
    if pool:
        return random.choice(pool)

    # Priority 2: unseen today (ignore same-run uniqueness — small team)
    pool = [q for q in questions if question_id(q) not in user_sent_today]
    if pool:
        return random.choice(pool)

    # Priority 3: full reset (user has exhausted all questions today)
    return random.choice(questions) if questions else None


# ── Telegram ──────────────────────────────────────────────────────────────────

DAILY_TOTAL = 5

ORDINALS_ES = {1: "Primera", 2: "Segunda", 3: "Tercera", 4: "Cuarta", 5: "Quinta"}


COUNTRY_FLAG = {
    "mexico":   "🇲🇽",
    "colombia": "🇨🇴",
    "chile":    "🇨🇱",
    "peru":     "🇵🇪",
    "all":      "🌎",
}
DIFF_ES = {"easy": "Fácil", "medium": "Medio", "hard": "Difícil"}


def _meta_line(q: dict) -> str:
    product  = (q.get("product") or "general").capitalize()
    country  = q.get("country", "all")
    flag     = COUNTRY_FLAG.get(country, "🌎")
    country_label = country.capitalize() if country != "all" else "Todos los países"
    diff     = DIFF_ES.get(q.get("difficulty", ""), q.get("difficulty", ""))
    return f"📦 {product}  {flag} {country_label}  🎯 {diff}"


def format_message(q: dict, question_num: int) -> str:
    ordinal = ORDINALS_ES.get(question_num, f"#{question_num}")
    meta   = _meta_line(q)
    header = f"*{ordinal} pregunta del día — {question_num}/{DAILY_TOTAL}*\n_{meta}_\n\n"
    prompt = q["prompt"]
    qtype  = q.get("question_type", "open_ended")

    if qtype == "multiple_choice":
        choices_text = "\n".join(f"  *{c['key']})* {c['text']}" for c in q.get("choices", []))
        return f"{header}{prompt}\n\n{choices_text}\n\nResponde con la letra de tu opción (A, B, C…)"

    if qtype == "yes_no":
        return f"{header}{prompt}\n\nResponde *Sí* o *No*"

    return f"{header}{prompt}\n\nResponde con texto libre o un voice note en donde se escuche bien tu voz."


def send_telegram(chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        result = json.loads(urlopen(req).read())
        return result.get("ok", False)
    except HTTPError as e:
        print(f"❌ Telegram error for {chat_id}: {e.code} — {e.read().decode()}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set")
        return

    users = load_enrolled_users()
    if not users:
        print("⚠️  No enrolled users")
        return

    questions = load_all_questions()
    if not questions:
        print("⚠️  No questions found in data/")
        return

    state = load_state()
    per_user = state["per_user"]

    # Shuffle user order so delay accumulation is unpredictable
    random.shuffle(users)

    already_picked_this_run: set[str] = set()
    success = 0

    for user in users:
        cid = str(user["chat_id"])
        name = user.get("name", cid)

        user_sent = per_user.get(cid, [])
        q = pick_for_user(questions, user_sent, already_picked_this_run)
        if not q:
            print(f"  ⚠️  No question available for {name}")
            continue

        qid = question_id(q)
        question_num = len(user_sent) + 1

        # Random stagger: sleep 0–9 minutes before sending to this user
        delay = random.randint(0, MAX_DELAY_SECONDS)
        print(f"  ⏳ {name}: waiting {delay}s before sending…")
        time.sleep(delay)

        text = format_message(q, question_num)
        if send_telegram(cid, text):
            print(f"  ✅ {name} — {q['prompt'][:60]}…")
            per_user[cid] = user_sent + [qid]
            already_picked_this_run.add(qid)
            success += 1
        else:
            print(f"  ❌ {name}")

    state["per_user"] = per_user
    save_state(state)

    print(f"\n✅ Sent to {success}/{len(users)} users")


if __name__ == "__main__":
    main()
