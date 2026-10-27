---
status: accepted
date: 2026-10-27
supersedes: D24 (plan.md)
---
# The web UI is a React app over the JSON API, replacing the Jinja + htmx pages

D24 chose server-rendered Jinja + htmx to keep the app free of a Node toolchain. The redesign (D35, D36) asks for a three-pane layout that updates in place: a Tag tree, an Item list with search as you type, and a reading pane, plus keyboard navigation, drawers, inline tag and note edits and an add dialog. In htmx each of those interactions is a partial template wired to two or three targets, with state spread across the URL, the DOM and the templates, plus hand-written JS for what htmx doesn't cover. We chose a React + TypeScript single-page app that talks only to the existing JSON API (the same one the extension and the MCP server use), because one client-side state model with one component per pane is the cleaner structure for this design, and mainstream component libraries give accessible dialogs, menus and comboboxes without hand-written CSS and JS.

**Considered:** keeping htmx and restyling the existing pages (no rewrite, no new toolchain, but the in-place three-pane behaviour tangles); building one slice both ways before deciding (skipped; the trade-off was clear enough from the mockup).
**Consequences:** the app gains a Node toolchain (the repo already has one for the extension); `kb/ui.py`, `kb/templates` and their tests are replaced; the JSON API grows the reads the pages used to get straight from storage (an Item list, Tag counts, which Tags can be deleted); the UI's login has to work with the bearer-only API. The backend stays the single place for every rule; the frontend holds view state only.
