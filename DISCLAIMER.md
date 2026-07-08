# Disclaimer

**This project is provided "AS IS", without warranty of any kind, express or implied.**

Read this document in full before using, forking, or deploying Sales Coach Bot in any real environment.

---

## No liability

The author(s) and contributors of Sales Coach Bot are **NOT responsible** for any of the following outcomes resulting from your use of this software:

### Technology & operations
- Any bugs, defects, crashes, data loss, data corruption, or downtime
- Security vulnerabilities in this codebase, its dependencies (Python packages, upstream libraries), or the underlying platform (operating system, container runtime, cloud provider)
- Security vulnerabilities or service disruptions of third-party services this project integrates with, including but not limited to: Telegram, OpenAI, Anthropic, Resend, Railway, PostgreSQL providers, SMTP providers
- Loss or exposure of API keys, credentials, database contents, or session tokens
- Inability to use the software or achieve any specific business result

### Financial
- Costs incurred from third-party APIs (OpenAI/Anthropic tokens, Resend email volume, SMTP fees, cloud hosting, database hosting, storage, bandwidth)
- Unexpected billing spikes from misconfiguration, prompt injection, abuse, or runaway loops
- **You are solely responsible for setting spending limits, monitoring usage, and controlling costs on every third-party service.**

### Legal & compliance
- Compliance with local, national, or international regulations, including but not limited to:
  - Data protection laws (GDPR, CCPA, LGPD, LFPDPPP, PIPEDA, etc.)
  - Employee monitoring and consent regulations in your jurisdiction
  - Labor laws related to performance evaluation and dismissal
  - Industry-specific regulations (HIPAA, PCI-DSS, SOX, financial services, healthcare, etc.)
  - Cross-border data transfer requirements
- Any legal claims, disputes, fines, or enforcement actions against you or your organization
- **You are solely responsible for conducting your own legal review before deploying this system, especially before enrolling employees.**

### AI outputs
- Accuracy, correctness, or appropriateness of LLM-generated grading, feedback, coaching messages, or automated reports
- Bias, discrimination, hallucination, or offensive content produced by the LLM
- HR, disciplinary, promotion, compensation, or termination decisions made in whole or in part based on data collected by this system
- **LLM grading should be treated as one signal among many, never as the sole basis for consequential decisions about people.**

### Privacy & data
- Storage, transmission, retention, deletion, or exposure of personally identifiable information (PII) belonging to your employees, contractors, customers, or third parties
- Data breaches involving your database or logs
- Compliance with your organization's information security policies
- **You must obtain explicit, informed consent from every person enrolled in the system before collecting any data about their performance.**

---

## Your responsibilities before deploying

At minimum:

1. **Security review.** Audit the code, dependencies (`pip audit` or Snyk), and infrastructure. Do not assume the maintainer has done this.
2. **Threat modeling.** Understand your attack surface: Telegram bot token exposure, OpenAI key exposure, database access, dashboard authentication, session hijacking.
3. **Rotate keys and secrets** on a regular schedule.
4. **Set spending limits** on every third-party API you use (OpenAI dashboard supports this natively).
5. **Legal review.** Consult your legal or compliance team about employee monitoring, data collection, and cross-border data transfer before enrolling any user.
6. **Employee consent.** Get explicit, documented, opt-in consent from each rep before enrolling them. Explain what data is collected, how it's used, how long it's retained, and how they can opt out.
7. **HR guardrails.** Establish clear policies on how the collected data may (and may not) influence HR decisions.
8. **Backup strategy.** Set up regular backups of your database. This project does not do that for you.
9. **Bias review.** Periodically sample LLM-generated grades and feedback to check for bias, especially against non-native language speakers or specific demographic groups.
10. **Incident response plan.** Know what you'll do if the bot token, database, or LLM keys are compromised.

---

## No support, no SLA

- There is no service-level agreement of any kind
- Response times to issues, discussions, or pull requests are best-effort and not guaranteed
- The maintainer(s) may abandon the project, break APIs, or archive the repository at any time without notice
- Neither the maintainer(s) nor any contributor is available for consulting, custom development, or emergency support unless explicitly contracted for that purpose in a separate written agreement

---

## Terms adopted by using this project

By cloning, forking, running, deploying, modifying, or distributing this software, you acknowledge that you have read this document and agree to accept full and sole responsibility for your instance and for any consequences arising from its use.

If you do not accept these terms, do not use this software.

See [`LICENSE`](LICENSE) (MIT) for the formal warranty disclaimer.

---

*Este documento se proporciona en inglés por ser el idioma estándar de licenciamiento de software. Si operas en un país cuya legislación exige documentación legal en otro idioma, consulta con un abogado local antes de deployar.*
