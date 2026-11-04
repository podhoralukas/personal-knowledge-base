---
status: accepted
date: 2026-11-02
amended: 2026-11-04
---
# Summary Files, not OpenSearch, are the system of record for Sessions

The Owner wants Session Summaries readable on their own, outside the knowledge base, and the knowledge base's Sessions rebuildable whatever happens to its indices. So, as an exception to ADR 0001, when an agent sends a Session Summary the app writes it to a Summary File, in a folder given by an environment variable (the Owner may point it at a synced notes folder; the public example stays generic), and imports it from that file. An idempotent import catches the knowledge base up from the folder, so its Sessions can always be rebuilt from the files. A summary could also be re-created later from its Transcript, as an after-the-fact one, but only while the Transcript exists, and not as the agent in the Session would have written it.

**Considered:** the knowledge base as the only copy, protected by the OpenSearch snapshots (snapshots are not readable as text); writing the file and the knowledge base independently (the two drift with no rule for which one wins); the agent writing the file itself so that a summary survives Docker being down (every agent would have to know the folder, the file naming and the format, while Docker is up whenever the PC is on and a failed summary is cheap to retry).
**Consequences:** a Session Summary exists twice; the Summary File wins on any disagreement. There is one Summary File per Version, never rewritten, so a rebuild restores each Session's full history. The Session Summary is read-only in the knowledge base (Annotations stay editable, as they never reach the file): changing it means asking the agent for a new one. The folder → Project mapping lives in the same folder, not in this public repo, so it is personal and a rebuild from the folder restores the Projects too. With Docker down, nothing is written: the agent says so and the summary is retried.
