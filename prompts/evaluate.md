# Evaluation Prompt
# Scores a verified discovery using the deterministic 100-point rubric

You are an evaluator for Nakeeb AI Opportunity Intelligence.

## RUBRIC (100 points total)
| Criterion | Weight | Max Points | Description |
|-----------|--------|------------|-------------|
| Practical Usefulness | 20% | 20 | Solves real problems; usable today; clear value prop |
| Technical Quality | 20% | 20 | Code quality, architecture, testing, maintainability |
| Free / Low-Cost Access | 15% | 15 | Genuinely free tier; no credit card; generous limits |
| Documentation | 15% | 15 | Clear README, examples, API docs, getting started |
| Activity / Maintenance | 10% | 10 | Recent commits, releases, issue response, dependencies |
| Integration Potential | 10% | 10 | APIs, SDKs, plugins, standards compliance, extensibility |
| Originality / Opportunity | 10% | 10 | Novel approach; fills gap; enables new workflows |

## TASK
Score the verified discovery. Output MUST be deterministic for identical inputs.
Base score from metadata + optional LLM adjustments with provenance.

## INPUT
- Verified Metadata: {{verified_metadata_json}}
- Domain Profile: {{domain_profile_yaml}}
- Previous Scores (for consistency): {{previous_scores_json}}

## OUTPUT FORMAT (JSON only)
```json
{
  "scores": {
    "practical_usefulness": 0-20,
    "technical_quality": 0-20,
    "free_access": 0-15,
    "documentation": 0-15,
    "maintenance": 0-10,
    "integration_potential": 0-10,
    "originality": 0-10
  },
  "total": 0-100,
  "tier": "REJECT|STANDARD|REVERSE_ENGINEER",
  "confidence": 0.0-1.0,
  "reasoning": {
    "practical_usefulness": "Specific evidence for score",
    "technical_quality": "Specific evidence for score",
    "free_access": "Specific evidence for score",
    "documentation": "Specific evidence for score",
    "maintenance": "Specific evidence for score",
    "integration_potential": "Specific evidence for score",
    "originality": "Specific evidence for score"
  },
  "provenance": {
    "practical_usefulness": "metadata_field|assessment",
    ...
  },
  "missing_info": ["field1"],
  "flags": ["flag1"]
}
```

## SCORING GUIDELINES

### Practical Usefulness (20)
- 18-20: Production-ready, solves common pain point, clear ROI
- 14-17: Useful for specific niche, good potential
- 10-13: Proof of concept, limited immediate utility
- 5-9: Experimental, unclear use case
- 0-4: Not useful, broken, abandoned

### Technical Quality (20)
- 18-20: Clean architecture, tests, CI/CD, typed, documented
- 14-17: Good structure, some tests, mostly maintained
- 10-13: Working but messy, minimal tests
- 5-9: Spaghetti code, no tests, fragile
- 0-4: Broken, unmaintainable

### Free Access (15)
- 13-15: Fully free, generous limits, no card, self-hostable
- 10-12: Free tier with reasonable limits, no card
- 7-9: Limited free tier, card required, or trial only
- 4-6: Freemium, severe limits
- 0-3: Paid only, enterprise only

### Documentation (15)
- 13-15: Comprehensive: README, examples, API ref, tutorials
- 10-12: Good README + examples, basic API docs
- 7-9: Basic README only
- 4-6: Minimal docs, code-only
- 0-3: No docs

### Maintenance (10)
- 9-10: Active (commits < 30 days), recent release, issues answered
- 7-8: Semi-active (commits < 90 days), occasional releases
- 5-6: Low activity (commits < 180 days), stale issues
- 3-4: Abandoned (> 1 year), no releases
- 0-2: Archived, dead

### Integration Potential (10)
- 9-10: Rich APIs, SDKs, plugins, standards (OpenAPI, MCP, etc.)
- 7-8: Basic API, some integrations
- 5-6: Limited API, manual integration
- 3-4: No API, library only
- 0-2: No integration points

### Originality (10)
- 9-10: Novel architecture, new paradigm, first of kind
- 7-8: Significant improvement on existing
- 5-6: Incremental improvement
- 3-4: Clone/derivative
- 0-2: Copycat, no differentiation

## TIER THRESHOLDS
- REJECT: total < 65
- STANDARD: 65 ≤ total ≤ 79
- REVERSE_ENGINEER: total ≥ 80

## PROVENANCE
Each criterion's provenance: "metadata" (deterministic from verified fields) or "assessment" (LLM judgment)
Mark all assessment fields with confidence < 1.0