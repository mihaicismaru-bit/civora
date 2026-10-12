# PUBLIC PRESENCE OS migration

Canonical standalone repository: https://github.com/mihaicismaru-bit/public-presence

Migrated main: d5dd4b250ed5f8447093ad4ef39c33ed1e2a9e31. Original PPOS source tree was unchanged between CIVORA source snapshots 424cb4e7ec6860998bdfb9cb3b2a5f7829899426 and 871996e9025c3584dcfee60babcaf8ab31e15bab. Both Graph 10 fixes (#1368 and #1372) are preserved; #1359/#1361 guards are reconciled in standalone main.

This cleanup removes only the PPOS subtree, its two Actions workflows and its README table row. All other products and shared utilities remain byte-identical. Historical CIVORA commits and PRs remain accessible; standalone filtered branch/PR archive tags and the old-to-new commit map preserve PPOS-only recovery evidence.

Rollback after merge: revert the cleanup merge commit with GitHub Revert or `git revert -m 1 CLEANUP_MERGE_SHA`, then review and merge the generated rollback PR. Before merge, closing this PR leaves CIVORA main unchanged. Do not dispatch restored legacy shadow workflows or activate writes during rollback.

No environments or secrets were copied or deleted. Configure public-presence-shadow in the standalone repository manually. Retain KILL_SWITCH=true, LIVE_WRITE=false and Threads disabled. Source environment retirement belongs to owner credential management after the separate environment is provisioned.
