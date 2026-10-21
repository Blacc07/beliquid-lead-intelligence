# Reviewer Guide: Evidence-Backed BeLiquid Prospect Qualification

## Purpose and non-negotiable rules

This guide is the operating procedure for the existing six-criterion **proposed pilot baseline** in `config/qualification_criteria.json`. It does not introduce or change the scoring model. The weights and definitions are a hypothesis, not a validated sales model.

- Review a prospect by its exact `chain:contract_address` identity from `prospect-review.csv` or `prospect-review.json`. Matching is case-insensitive, but never substitute a different contract or chain.
- Record only findings supported by sources you actually opened and checked. Never infer a fact, contact, identity, risk status, or buying intent from a token name, volume, promotion, or an unverified profile.
- Keep evidence observation time separate from event date. Use ISO 8601 timestamps with an explicit timezone, e.g. `2026-10-21T14:30:00Z` or `2026-10-21T15:30:00+01:00`.
- `unknown` means not established from the evidence reviewed; it does not mean zero, false, absent, safe, or unsuitable.
- Identity and security holds are independent of the qualification score. A high score cannot override a `manual_hold`.
- The workflow does not send outreach. A score or route is not permission to contact a prospect.

## The six criteria and evidence standards

The configured weights total 100 and are unchanged by reviewer input.

| Criterion key | Weight | What supports `confirmed` | When `not_present` is defensible | Keep `unknown` when |
|---|---:|---|---|---|
| `service_fit_and_demonstrated_need` | 25 | Timestamped spread/depth observations, slippage or fragmented-liquidity analysis, or an official statement about liquidity/market-making needs | You checked relevant sources and the defined need/initiative is not supported by those sources; describe the scope checked | There is no reliable market-quality observation or explicit initiative; do not infer need from age, price moves, volume, or promotion alone |
| `market_activity_and_commercial_potential` | 20 | Timestamped activity and liquidity data with named venues/pairs and context; preferably compare depth, spread, venue coverage, and consistency | Reviewed comparable data does not support meaningful/sustained activity or a plausible service opportunity; state the period and venues checked | Data is missing, stale, incomparable, or only one uncontextualized volume snapshot |
| `buying_trigger_and_timing` | 20 | Dated official launch/TGE, listing/new pair, venue expansion, or documented market-quality issue with source and timing | You checked relevant official sources for a defined period and found no qualifying trigger; document the scope rather than claiming none exists everywhere | No reliable dated trigger has been reviewed or the event/relevance is ambiguous |
| `project_credibility_and_team_access` | 15 | Cross-verified chain/contract/project identity, credible operating activity, and a legitimate public business-contact path | Sources reviewed contradict the claimed identity, activity, or access path; identity conflict must also be recorded in the independent identity/risk file | Contract/domain/project identity or a legitimate contact route remains ambiguous |
| `growth_and_strategic_potential` | 10 | Verifiable product releases, integrations, ecosystem expansion, or dated milestones attributable to the project | Reviewed sources do not substantiate the relevant growth claims within the documented scope | Claims are promotional, undated, uncorroborated, or hard to distinguish from paid boosting |
| `security_and_reputational_integrity` | 10 | A proportionate, documented check of authoritative identity/contract sources, relevant security evidence, and reputable reporting finds no material unresolved concern | Evidence reviewed supports a specific adverse concern or the defined integrity claim is not supported; record the source and context | Review is incomplete, security data is unavailable, or a concern is unresolved. Unknown is never “safe.” |

**Important status distinction:** `not_present` is a positive reviewer conclusion that the evidence reviewed does not support the criterion. It is not a substitute for missing research. Use `unknown` when evidence is insufficient. Both `confirmed` and `not_present` require at least one evidence URL and a corresponding timezone-aware evidence timestamp.

A buying-trigger event record is supporting material, not an automatic criterion assessment. The reviewer must separately assess `buying_trigger_and_timing` against its definition in the criterion review file.

## Repeatable review procedure

### 1. Generate and preserve the batch

1. Run **Actions → BeLiquid Pipeline Health Check → Run workflow**, or use the next scheduled run.
2. Download the `beliquid-prospect-review-<run number>` artifact from that exact run.
3. Preserve the original `prospect-review.csv`, `prospect-review.json`, and `pipeline-summary.json` unchanged as the batch snapshot. Artifacts currently expire after 14 days; save the files in your approved internal evidence store if longer retention is required.
4. Record the run URL/number and batch date in your review log. Do not treat a later run as the same batch: candidate lists and metrics can change.

### 2. Select a prospect and establish identity first

1. Start with the exported row; copy its exact `chain` and `contract_address`.
2. Open candidate URLs as leads for research, not proof of official identity. Cross-check chain and contract against authoritative project documentation and a credible independent source.
3. If chain/contract or official identity conflicts, record the evidence in `config/identity_risk_reviews.json` as `identity_status: "mismatch"` and stop qualification work pending a human decision. Do not “fix” the export by silently replacing the contract.
4. Review security/integrity separately. A substantiated concern is `risk_status: "concern"` and routes to `manual_hold`. Use `clear` only after a proportionate, documented check; absence of a quick search result is not enough.
5. If either check is unresolved, keep its status `unknown`; the route remains `research` until both identity is `verified` and risk is `clear`. A mismatch or concern always forces `manual_hold`.

### 3. Record criterion findings

Edit `config/criterion_reviews.json` in the repository or in a controlled working copy. Add a key for the prospect in the form `<chain>:<contract_address>`; under it, use only the exact criterion keys above. Do not add weights or change the six criteria.

Illustrative structure only — these URLs and timestamps are placeholders, not evidence about a real prospect:

```json
{
  "schema_version": 1,
  "reviews": {
    "example-chain:ExampleContract123": {
      "service_fit_and_demonstrated_need": {
        "status": "confirmed",
        "evidence_urls": [
          "https://example.org/research/market-quality"
        ],
        "evidence_timestamps": [
          "2026-10-21T14:30:00Z"
        ],
        "note": "Illustrative only: state what the cited source demonstrates and the venue/pair/period reviewed.",
        "review_flag": null
      },
      "market_activity_and_commercial_potential": {
        "status": "unknown",
        "evidence_urls": [],
        "evidence_timestamps": [],
        "note": "Illustrative only: comparable time-series evidence has not yet been reviewed.",
        "review_flag": null
      }
    }
  }
}
```

For every `confirmed` or `not_present` finding:
- `evidence_urls` must contain absolute HTTP(S) URLs.
- `evidence_timestamps` must contain the same number of timestamps, each ISO 8601 with a timezone. Each timestamp means when the reviewer observed/checked that evidence, not the event date.
- Include a concise note that explains the conclusion and scope. Keep multiple URLs and timestamps paired by array position.
- Do not fabricate a timestamp from the page's publication date. If observation time is not known, check the source now and record the current observation time.
- For `unknown`, evidence arrays may be empty; a note should explain what remains unresolved.

### 4. Record dated buying triggers separately

Use `config/buying_trigger_reviews.json` for event-level observations such as `exchange_listing`, `new_trading_pair`, `token_launch_or_tge`, `venue_expansion`, `documented_liquidity_issue`, `milestone_or_campaign`, `token_unlock`, or `other`. Each inferred/verified trigger needs its own evidence URL, timezone-aware `observed_at`, and concise `summary`; `event_date` is optional and uses `YYYY-MM-DD`. A trigger's `status` is `verified`, `inferred`, or `unknown`, not a criterion status. Never convert a rumor, volume metric, paid promotion, or social engagement count into a verified trigger.

### 5. Maintain the independent identity/risk record

Use `config/identity_risk_reviews.json`. Supported identity statuses are `unknown`, `verified`, and `mismatch`; supported risk statuses are `unknown`, `clear`, and `concern`. Every non-unknown identity or risk status needs its own evidence URL and timezone-aware timestamp. Record a reviewer note describing sources checked and any limitation. `mismatch` or `concern` forces `manual_hold`; only `verified` plus `clear` reaches `business_development_review`. Unknowns remain in `research`.

### 6. Validate, regenerate, and reconcile exports

1. Ensure each review file remains valid JSON and each review key uses the exported chain and contract exactly.
2. Run the offline tests locally before committing:
   ```bash
   PYTHONPATH=src python -m unittest discover -s tests -v
   ```
3. Commit review files only after a second reviewer checks evidence and status choices. Do not commit credentials or private personal information. The repository is public, so consider whether prospect-specific reviewer notes belong in the repository at all; use an approved private store if needed.
4. Run the pipeline again so exports consume the reviewed files. Inspect the artifact from that run, not an older artifact.
5. Compare `prospect-review.csv` with `prospect-review.json` for each reviewed prospect: chain, contract, six criterion statuses, score/withheld state, evidence coverage, criterion evidence URL/timestamp/note, identity/risk statuses, and action route must agree. CSV is a review convenience; JSON is structured output. If they disagree, do not use the record for decisions—raise a defect and retain both artifacts.
6. Confirm `pipeline-summary.json` counts reviewed prospects and issued/withheld scores consistently. Check that outreach remains disabled. The workflow now runs `python -m beliquid.validate_review_batch --artifacts-dir artifacts --write-manifest`; this fails the job if review keys do not match the current batch, CSV/JSON fields disagree, a score is issued below the threshold, a risk hold fails to route to `manual_hold`, or outreach is enabled.
7. Preserve `audit-manifest.json` with the exports. It records the Actions run/commit context and SHA-256 hashes of review/config inputs and generated exports. Hashes establish file integrity/provenance, not the truth of the cited evidence.

## Controlled pilot-validation report

Each successful pipeline run also emits `pilot-validation.json`, `pilot-validation.csv`, and `pilot-validation.md`. The report deliberately separates engineering validation (unit tests in CI, schema checks, and CSV/JSON parity) from prospect evidence quality (criterion coverage, unknowns, and review completion). It does not change reviewer statuses or establish whether sources are truthful.

The record-level queue uses these process labels:

- `not_started`: no criterion, identity/risk, or trigger review is recorded.
- `in_progress`: some review exists, but required criterion evidence, identity/risk clearance, or flag resolution is incomplete.
- `ready_for_second_review`: all six criteria have non-unknown statuses with paired evidence URLs/timestamps; identity is `verified`, risk is `clear`, identity/risk evidence is present, and no review flags remain.
- `blocked_manual_hold`: an identity mismatch or risk concern requires human resolution.

“Ready for second review” is a queueing recommendation, not proof a second reviewer has approved the record. It does not authorize outreach. Unknown statuses remain unknown, and source truth still requires human checking.

## Scoring and routing safeguards

- Criterion weights remain 25 / 20 / 20 / 15 / 10 / 10.
- Only explicit human criterion assessments count toward evidence coverage. Unknown criteria do not count as assessed weight.
- The current minimum evidence coverage is 60%. At 45% coverage, a score is withheld. At 60% or above, a score may be calculated from assessed criteria; it is not proof of buyer intent, fit, or permission to contact.
- Market research priority is a separate unvalidated heuristic, not the qualification score.
- Identity/risk routing is independent: mismatch or concern → `manual_hold`; verified plus clear → `business_development_review`; otherwise → `research`.
- Outreach authorization is a separate human decision after evidence review, qualification, and business-development approval. This repository has no automatic send action; `outreach_enabled` remains `false`.

## Audit record checklist

For each reviewed batch, retain (in an approved location) the Actions run URL/number, original artifact, review-file version/commit, reviewer and review date in your internal log, evidence URLs, observation timestamps, rationale/scope notes, unresolved flags, CSV/JSON reconciliation outcome, and the human decision/approver. Current JSON review schemas capture evidence and notes but do not have dedicated reviewer-identity or review-completed-at fields; record those in the separate review log until that schema is deliberately extended.
