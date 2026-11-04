---
name: session-summary
description: Save a Session Summary to the Owner's knowledge base. Use when the Owner asks to summarise a session, this one (at its end or part-way through) or a past one.
---

# Session Summary

A Session Summary is an archive entry: the Owner finds it months later by searching for a word or a meaning, without this conversation to hand. What they come back for is what was decided and why, and how a problem was worked out, in the exact words they would search for.

For a past Session, one the Owner names by id or wants to pick, follow [after-the-fact.md](after-the-fact.md) instead of steps 1 and 3.

## 1. Identify this Session

| Field | Claude Code | Codex |
|---|---|---|
| `agent` | `claude-code` | `codex` |
| `session_id` | `$CLAUDE_CODE_SESSION_ID` | `$CODEX_SESSION_ID` |
| `transcript_path` | `ls ~/.claude/projects/*/<id>.jsonl` | `ls ~/.codex/sessions/*/*/*/rollout-*-<id>.jsonl` |

- `folder`: `git rev-parse --show-toplevel 2>/dev/null || pwd`
- `branch`: `git branch --show-current`
- `repo_url`: `git remote get-url origin`, with any credentials in it removed
- `model`: the model you are running as

Done when you have `agent`, `session_id` and `folder`. Leave out whichever of the others do not apply.

## 2. Confirm a personal Session

When `$CLAUDE_CODE_ENTRYPOINT` is `claude-desktop`, the Session may be personal. Ask the Owner whether to summarise it, and continue only on an explicit yes.

## 3. Gather the whole Session

Cover the Session from its start up to now, including anything an earlier summary of it already said: the newest summary is the one search shows.

If your context was compacted, read the Transcript for the part you no longer hold.

Done when every decision taken and every problem worked out in the Session is accounted for.

## 4. Write the summary

The tool's schema says what each field holds. On top of that:

- **Decisions and Problems matter most.** Spend the words there: a decision without its reason, or a fix without its cause, is of little use later.
- **Exact words.** Use identifiers, file names, commands and error strings verbatim, and collect them in `keywords`.
- **Size follows the Session.** A small one is two or three lines; leave out every section it has nothing for.
- **Language.** Write in the language the Owner wrote most of their prompts in.
- **Redaction.** Replace tokens, keys, `.env` values and internal hostnames with a description of what they were.

Done when you have reread every field for secrets.

## 5. Save it

Call `save_session_summary` on the `kb` MCP server.

- **It answers that the folder has no Project.** Ask the Owner: an existing one (the `project/` Tags from `list_tags`), a new `project/<name>`, or none. Call again with their answer as `project`. If they want to be asked every time for this folder, as for a home folder, add `always_ask`.
- **The server cannot be reached.** Tell the Owner the knowledge base is down and nothing was saved, and show them the summary so it can be saved later.
- **It refuses the summary.** Correct what it names and call again.

Done when the tool has returned a link. Give the Owner that link.
