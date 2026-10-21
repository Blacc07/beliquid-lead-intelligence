# Automated research queue policy

The pipeline runs without mandatory human review. It discovers/enriches prospects, researches identity and risk, investigates market quality and buying triggers, collects criterion evidence, calculates scores only when the existing evidence threshold is met, and emits an auditable disposition.

- Identity and risk research runs first, but an unresolved result does not stop automated commercial research.
- Only `identity_status=verified` plus `risk_status=clear` can receive `clearance_status=cleared`.
- Unknown or unresolved identity/risk remains `clearance_status=unresolved` and is excluded from the cleared/qualified list, even if commercial evidence is promising.
- A documented identity mismatch or risk concern produces an automated held disposition and blocks downstream qualification actions.
- A completed research task records work performed, not a verified identity, clear risk result, or qualification decision.
- Unsupported scores remain withheld; missing evidence must not be converted to a zero or a negative finding.
- Completed tasks are suppressed only while their input fingerprint matches the current prospect record.
- No independent human-review task is generated. Pipeline validation, schema checks, and audit hashes remain automated.
- Automated outreach remains disabled.
