# Knowledge Bases

This folder holds the reference documents the LLM grader uses when evaluating
open-ended answers. When a question is tagged with a product/service, the
grader looks up the matching `.txt` file here and injects it as context.

## Naming convention

The file name must match the question's `product` tag exactly:

- `product_a.txt` → questions with `product = "product_a"`
- `product_b.txt` → questions with `product = "product_b"`
- `general.txt`   → fallback for untagged questions

If no matching file is found, the grader still works — it just relies on the
question's own rubric (`must_have_concepts`, `ideal_answer`) instead of a KB.

## Adding a knowledge base for your company

1. Write or export the service description / FAQ / playbook as plain text
2. Save it as: `data/knowledge_bases/<your_service_name>.txt`
3. Make sure questions for that service carry a `product` tag of the same name
4. Add the service name to `VALID_SERVICES` in your `.env`
   (e.g. `VALID_SERVICES=product_a,product_b,onboarding,general`)

## Tips

- Keep each file focused (< 8 KB works best; LLM has better recall on shorter context)
- Use headings and bullet points; the grader parses them well
- Update the file any time your product changes — no code deploy needed
