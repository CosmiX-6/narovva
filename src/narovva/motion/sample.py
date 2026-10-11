"""Sample deck covering every slide kind, for previewing/rendering the motion
reel without running the news pipeline:  python -m narovva.motion [out.mp4]"""

from __future__ import annotations

SAMPLE_SLIDES: list[dict] = [
    {"kind": "hook", "kicker": "AI", "heading": "OpenAI just made its models three times cheaper to run", "body": "Here is what changed, and who pays.", "duration": 4.6},
    {"kind": "text", "kicker": "THE DETAILS", "heading": "A new pricing tier lands today", "body": "Inference costs drop for every model in the lineup, with the biggest cuts on the largest ones.", "duration": 5.0},
    {"kind": "stats", "kicker": "BY THE NUMBERS", "heading": "What shifted", "facts": ["67% cheaper per token", "3.2x faster responses", "$1.2B saved by customers", "14 models updated"], "duration": 5.2},
    {"kind": "evidence", "kicker": "THE EVIDENCE", "heading": "What the filings show", "facts": ["Prices were cut on all API tiers", "Rate limits doubled for paid plans", "Batch jobs now cost half"], "duration": 5.0},
    {"kind": "timeline", "kicker": "TIMELINE", "heading": "How we got here", "timeline": [{"when": "Jan 2025", "what": "First price cut announced"}, {"when": "Jun 2025", "what": "Competitors respond"}, {"when": "Oct 2026", "what": "Three-times-cheaper tier ships"}], "duration": 5.0},
    {"kind": "money_flow", "kicker": "FOLLOW THE MONEY", "heading": "Where the savings go", "money": [{"actor": "Customers", "amount": None, "detail": "API spend"}, {"actor": "Cloud provider", "amount": "$0.4B", "detail": "Compute bill"}, {"actor": "Chipmaker", "amount": "$0.2B", "detail": "GPU purchases"}], "duration": 5.0},
    {"kind": "comparison", "kicker": "HEAD TO HEAD", "comparison": {"title": "Cost per million tokens", "label_a": "Before", "value_a": "$15", "label_b": "After", "value_b": "$5"}, "duration": 4.6},
    {"kind": "quote", "kicker": "IN THEIR WORDS", "quote": {"text": "Intelligence should be too cheap to meter.", "attribution": "Company spokesperson"}, "duration": 4.4},
    {"kind": "conclusion", "kicker": "WHY IT MATTERS", "heading": "Cheaper AI means more AI everywhere", "body": "Expect a wave of products that were too expensive to ship last year.", "duration": 4.8},
    {"kind": "cta", "heading": "Follow for daily AI breakdowns", "duration": 3.2},
]
