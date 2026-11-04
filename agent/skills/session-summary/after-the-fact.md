# A past Session

You were not in this Session, so its Transcript is your only source and the summary is marked `after_the_fact`. Then continue with step 4 of the skill.

## 1. Find the Transcript

- **By id:** `ls ~/.claude/projects/*/<id>.jsonl ~/.codex/sessions/*/*/*/rollout-*-<id>.jsonl`
- **By pick:** list the newest for the Owner to choose from, with each one's first prompt:
  - Claude Code: `ls -t ~/.claude/projects/<folder>/*.jsonl | head`, with every character of the folder's path other than letters, digits and `-` written as `-`
  - Codex: `grep -l '"cwd":"<folder>"' ~/.codex/sessions/*/*/*/rollout-*.jsonl`, newest first by the date in the name

## 2. Identify the Session

Each line of a Transcript is a JSON event.

| Field | Claude Code | Codex |
|---|---|---|
| `agent` | `claude-code` | `codex` |
| `session_id` | `sessionId` on any event | `payload.id` on the first event, `session_meta` |
| `folder` | `cwd` on the first `user` event | `payload.cwd` on the first event |
| `branch` | last `gitBranch` | `payload.git.branch` on the first event |
| `repo_url` | `git remote get-url origin` in the folder, if it still exists | `payload.git.repository_url` on the first event |
| `model` | `message.model` on the last `assistant` event | `payload.model` on the last `turn_context` event |

`transcript_path` is the file itself. When `entrypoint` on a Claude Code event is `claude-desktop`, confirm with the Owner as in step 2 of the skill.

## 3. Read it

A Transcript can run to megabytes, so give the reading to a subagent where you have one, and have it return the decisions with their reasons, the problems with their causes and fixes, and the exact identifiers and error strings.

The conversation is in these events; the rest is tool output and bookkeeping:

- Claude Code: `user` and `assistant` events, under `message.content`.
- Codex: `response_item` events whose `payload.type` is `message`. Text injected at the start of a turn also appears there as `role: user`; what the Owner typed is on `event_msg` events of type `item_completed`, item type `UserMessage`.

Done when the whole Transcript has been read, to its last event.

## 4. Save

Pass `after_the_fact: true`. The summary is filed under today's date, whenever the Session ran.
