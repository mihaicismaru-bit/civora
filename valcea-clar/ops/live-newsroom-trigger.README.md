# VÂLCEA CLAR Live Newsroom operator trigger

`live-newsroom-trigger.json` is an explicit operator request only. The operator bridge dispatches `.github/workflows/valcea-clar-newsroom-live.yml` and waits for that canonical writer. It does not write facts, editions, story pages, feeds, social state, or runtime itself.

Owner: `civora_site_engine`. Intent: `dispatch canonical live newsroom only`. Contract version: `1`. The trigger remains operator-driven; it is not a scheduler and has no publication authority of its own.

The canonical Live Newsroom remains the only publication path and retains all evidence, editorial-integrity, publication-hold, temporal-language and fail-closed gates. The operator bridge may only dispatch and observe that canonical workflow; it must not implement an alternate facts writer, story renderer, runtime writer, social publisher, or editorial bypass.

Trigger payloads must conform to `live-newsroom-trigger.schema.json`. Minimal shape:

```json
{
  "requested_at": "2026-08-22T10:00:00+03:00",
  "requested_by": "human_editor",
  "reason": "Run the canonical Live Newsroom for verified fresh material only.",
  "expected_story_ids": []
}
```
