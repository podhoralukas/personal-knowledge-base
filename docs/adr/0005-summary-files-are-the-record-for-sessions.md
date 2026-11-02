---
status: accepted
date: 2026-11-02
---
# Summary Files, not OpenSearch, are the system of record for Sessions

A Session Summary is written by the agent at the moment the Owner asks for it, and nothing can re-create it later with the same context; the knowledge base stack may not be running at that moment, and the Owner wants the summaries readable on their own, outside the knowledge base. So, as an exception to ADR 0001, the skill first writes a Summary File into a folder given by an environment variable (the Owner may point it at a synced notes folder; the public example stays generic), and only then sends the Session Summary to the knowledge base. An idempotent import catches the knowledge base up from the folder, so its Sessions can always be rebuilt from the files.

**Considered:** the knowledge base as the only copy, protected by the OpenSearch snapshots (snapshots are not readable as text, and a summary written while the stack is down would be lost); writing the file and the knowledge base independently (the two drift with no rule for which one wins).
**Consequences:** a Session Summary exists twice; the Summary File wins on any disagreement. There is one Summary File per Version, never rewritten, so a rebuild restores each Session's full history. The Session Summary is read-only in the knowledge base (Annotations stay editable, as they never reach the file): changing it means asking the agent for a new one. The folder → Project mapping lives in the same folder, not in this public repo, so it is personal and a rebuild from the folder restores the Projects too.
