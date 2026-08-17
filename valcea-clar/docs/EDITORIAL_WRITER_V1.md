# VÂLCEA CLAR — Editorial Writer v1

`manual_journalism_v1` is the evidence-bound writing layer between the verified fact registry and `story_ready`.

## Runtime contract

1. Discovery/monitors may create signals, but signals never authorize publication.
2. A new-style story supplies a `fact_kernel` whose headline, dek and atomic claims each reference URLs already present in the story source list.
3. `editorial_writer.py` chooses the journalistic format, validates the evidence chain and orders the claims according to `editorial/editorial_manual.json`.
4. Straight news, explainers and service journalism may remain auto-publish eligible if all existing evidence gates also pass.
5. Investigation and analysis products are composed but fail closed into `editorial_hold` until their additional editorial/reputational gate is satisfied.
6. Existing curated stories without a `fact_kernel` are validated and passed through byte-for-byte at the copy level; activation of the writer must not silently rewrite approved archive copy.
7. `generate_edition.merged_registry()` is the canonical activation point. `newsroom_decide.story_ready()` rejects incomplete writer provenance.
8. Social products continue to inherit the same canonical story identity after publication.

## Zero-LLM boundary

The v1 writer is a deterministic evidence compositor, not a free-form language model. It may select structure and order verified claims, but may not invent connective factual assertions, quotes, scenes, motives, causality or missing context. Richer generative writing can only be added later behind the same claim-level provenance and verification contract.

## Target flow

`signal → verification → fact kernel → Editorial Writer → story_ready → site → platform-native social products`
