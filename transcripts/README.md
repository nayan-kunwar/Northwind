# AI tool transcripts

The assignment asks for the full, unedited record of the AI sessions that contributed to
the submission. This folder contains:

- `full/` — the **authoritative, complete machine export** of the OpenCode session:
  every user message, assistant text, reasoning block, tool call with its input and
  output, system notice, compaction and model/agent switch. It is split into five
  Markdown parts plus an index because the session is about 1.8 MB of text.
- `session-01.md` — a short curated narrative of the same session, kept for reviewers who
  want the story (the pack, the first model, the wrong numbers, the corrections, the final
  run) without the tool noise. This is a summary, not the full record.
- `tool-log.md` — the commands and outputs that prove the repo runs: environment, git
  history, tests, the one-command run and the independent check.

## Full export

Start at [`full/README.md`](full/README.md). The export is generated from OpenCode's local
session store with:

```bash
python tools/export_transcript.py
```

The session used OpenCode with a DeepSeek V4.1 Flash agent. The AI wrote code, suggested
treatments and drafted documents; every number in the submission was checked against the
raw inputs, and every correction is recorded in `VALIDATION.md` with the commit that fixed
it.

**What the export omits:** embedded base64 attachments (the two assignment screenshots and
the PDF reads) are replaced by short placeholders so the file is readable. Nothing else is
removed. No secrets were found by the exporter's token scan; the git author email is a
placeholder.

**Snapshot note:** a transcript cannot include the messages written after it was exported.
The header of each part records the export time, and the live session may continue after
that point. The repository history is the authoritative record of what changed and when.
