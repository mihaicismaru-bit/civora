#!/usr/bin/env python3
from __future__ import annotations

import json
import sys


packet = json.load(sys.stdin)
hypothesis = packet["hypothesis"]
evidence_ids = [str(item["evidence_id"]) for item in packet.get("evidence", [])]
if not evidence_ids:
    print(json.dumps({
        "hypothesis_id": hypothesis["hypothesis_id"],
        "decision": "insufficient",
        "evidence_ids": [],
        "prohibited_overclaim": hypothesis.get("prohibited_overclaim")
    }, ensure_ascii=False))
    raise SystemExit(0)

first = evidence_ids[0]
construct = hypothesis["construct"]
print(json.dumps({
    "hypothesis_id": hypothesis["hypothesis_id"],
    "decision": "supported",
    "need_title": f"Synthetic need: {construct}",
    "need_statement": f"Synthetic acceptance evidence supports a material need related to {construct}.",
    "evidence_ids": evidence_ids,
    "confidence": 0.8,
    "ranking_dimensions": {
        "magnitude": 0.7,
        "severity": 0.6,
        "gap_strength": 0.7,
        "call_relevance": 0.9
    },
    "ranking_evidence": {
        "magnitude": [first],
        "severity": [first],
        "gap_strength": [first],
        "call_relevance": [first]
    },
    "prohibited_overclaim": hypothesis.get("prohibited_overclaim")
}, ensure_ascii=False))
