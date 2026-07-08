# Question Bank Format

Question banks are JSON files under `data/question_banks/`. Each file contains one bank; you can have as many as you want. Load them into the DB with:

```bash
python scripts/load_questions.py data/question_banks/YOUR_FILE.json
```

Use `--replace` to overwrite existing questions in that bank name.

## Top-level structure

```json
{
  "bank_name": "your_bank_name",
  "description": "Human description of what this bank covers",
  "questions": [
    { ... },
    { ... }
  ]
}
```

## Question object

### Common fields (all question types)

| Field | Required | Type | Notes |
|---|---|---|---|
| `prompt` | ✅ | string | The question text shown to the rep |
| `category` | ✅ | enum | `discovery` / `objections` / `qualification` / `closing` / `value_proposition` / `general` |
| `difficulty` | ✅ | enum | `easy` / `medium` / `hard` |
| `tags` | ✅ | array of strings | For KB routing and topic breakdowns |
| `question_type` | ✅ | enum | `open_ended` / `multiple_choice` / `yes_no` |
| `product` | ✅ | string | Must match a value in `VALID_SERVICES` (see `.env`) |
| `country` | ✅ | string | `all` or a country from `COUNTRIES` |

### `open_ended` questions

Add a `rubric` object:

```json
{
  "prompt": "How do you handle a 'too expensive' objection?",
  "category": "objections",
  "difficulty": "medium",
  "tags": ["saas", "objections", "pricing"],
  "question_type": "open_ended",
  "product": "product_a",
  "country": "all",
  "rubric": {
    "must_have_concepts": ["reframe to value", "quantify cost of inaction"],
    "good_to_have_concepts": ["case studies", "ROI"],
    "ideal_answer": "Never argue price directly. Reframe: 'compared to what?'. Quantify the cost of not solving the problem.",
    "reference_snippet": "Value-based objection handling"
  }
}
```

The grader uses:
- `must_have_concepts` for keyword pre-check
- `ideal_answer` as the reference for LLM scoring
- `reference_snippet` as a compact hint for the grader

### `multiple_choice` questions

```json
{
  "prompt": "Which of these best qualifies a deal?",
  "category": "qualification",
  "difficulty": "easy",
  "tags": ["saas", "qualification"],
  "question_type": "multiple_choice",
  "product": "product_a",
  "country": "all",
  "choices": [
    {"key": "A", "text": "The prospect has budget"},
    {"key": "B", "text": "Budget, timeline, and identified decision-maker"},
    {"key": "C", "text": "They asked for a demo"},
    {"key": "D", "text": "They downloaded a whitepaper"}
  ],
  "correct_answer": "B"
}
```

### `yes_no` questions

```json
{
  "prompt": "Should you always send pricing over email if asked?",
  "category": "closing",
  "difficulty": "easy",
  "tags": ["services", "pricing"],
  "question_type": "yes_no",
  "product": "product_a",
  "country": "all",
  "correct_answer": "no"
}
```

## Tips

- **Keep prompts short.** Reps read on their phone. One or two sentences max.
- **Test your questions yourself.** Load them, receive them via bot, and see if the grading feels fair.
- **Use `tags` for KB routing.** If a question is tagged `["saas", "objections"]`, the grader looks up `data/knowledge_bases/saas.txt` first.
- **`ideal_answer` matters most.** The LLM primarily grades against it. Make it explicit and complete.
- **Difficulty affects scoring weight** if you enable difficulty progression (off by default).
