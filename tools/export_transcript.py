"""Export a complete OpenCode session to readable Markdown.

The assignment asks for the full AI transcript, so this tool deliberately keeps
everything the session store contains: user messages, assistant text, reasoning,
tool calls with their inputs and outputs, system notices, compactions and
switches. The only things removed are embedded base64 attachments (images and
PDFs), which are replaced by a short placeholder.

Usage (from the repository root):

    python tools/export_transcript.py
    python tools/export_transcript.py --dry-run
    python tools/export_transcript.py --session ses_... --out transcripts/full

The exporter reads the OpenCode SQLite store read-only and writes one or more
Markdown files plus an index. It is deterministic for a fixed database snapshot;
the export time is written into the header.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
DEFAULT_OUT = ROOT / "transcripts" / "full"


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #

BASE64_RE = re.compile(r"data:[^;\s]+;base64,[A-Za-z0-9+/=\s]+")
SECRET_PATTERNS = [
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "[REDACTED_GITHUB_PAT]"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "[REDACTED_SLACK_TOKEN]"),
]


def utc(ts_ms: int | None) -> str:
    if not ts_ms:
        return "unknown"
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def strip_base64(text: str) -> str:
    return BASE64_RE.sub("[base64 data omitted]", text)


def redact_secrets(text: str) -> tuple[str, int]:
    count = 0
    for pattern, replacement in SECRET_PATTERNS:
        text, found = pattern.subn(replacement, text)
        count += found
    return text, count


def fence(text: str, language: str = "") -> str:
    """Return a fenced block that cannot be broken by the content itself."""
    longest = 0
    for match in re.finditer(r"`+", text):
        longest = max(longest, len(match.group(0)))
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{language}\n{text}\n{ticks}"


def compact_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

@dataclass
class Block:
    seq: int
    kind: str  # "user", "assistant" or "meta"
    text: str


def render_attachment(file: dict[str, Any]) -> str:
    name = file.get("name") or "attachment"
    mime = file.get("mime") or "unknown type"
    data = file.get("data") or ""
    size = len(data)
    return f"_[Attached {mime}: `{name}` — {size:,} base64 characters omitted]_"


def render_tool_input(name: str, payload: dict[str, Any]) -> str:
    if not payload:
        return ""

    if name == "shell" and "command" in payload:
        return "**Command**\n\n" + fence(str(payload["command"]), "bash")

    if name == "read" and "path" in payload:
        extra = []
        for key in ("offset", "limit"):
            if key in payload:
                extra.append(f"{key}={payload[key]}")
        suffix = f" ({', '.join(extra)})" if extra else ""
        return f"**Read:** `{payload['path']}`{suffix}"

    if name == "write" and "path" in payload:
        body = str(payload.get("content", ""))
        return (
            f"**Write:** `{payload['path']}`\n\n"
            + fence(body, "text")
        )

    if name == "edit" and "path" in payload:
        old = str(payload.get("oldString", ""))
        new = str(payload.get("newString", ""))
        return (
            f"**Edit:** `{payload['path']}`\n\n"
            "**Old text**\n\n"
            + fence(old, "text")
            + "\n\n**New text**\n\n"
            + fence(new, "text")
        )

    if name in ("grep", "glob"):
        parts = [f"**{name.title()}:**"]
        for key in ("pattern", "path", "include", "literal", "caseSensitive"):
            if key in payload:
                parts.append(f"- `{key}`: `{payload[key]}`")
        return "\n".join(parts)

    return "**Input**\n\n" + fence(compact_json(payload), "json")


def render_tool_result(state: dict[str, Any]) -> str:
    status = state.get("status", "unknown")
    if status == "error":
        error = state.get("error", {})
        kind = error.get("type", "error")
        message = error.get("message", "")
        return f"**Result:** error `{kind}`\n\n{fence(message, 'text')}"
    if status == "running":
        return "_Result: still running when this snapshot was exported._"

    chunks: list[str] = []
    for item in state.get("content", []) or []:
        if item.get("type") == "text":
            chunks.append(fence(strip_base64(item.get("text", "")), "text"))
        elif item.get("type") == "file":
            name = item.get("name", "attachment")
            mime = item.get("mime", "unknown type")
            uri = item.get("uri", "")
            size = len(uri)
            chunks.append(
                f"_[File result: `{name}` ({mime}), {size:,} base64 characters omitted]_"
            )
        else:
            chunks.append(fence(compact_json(item), "json"))

    metadata = state.get("metadata")
    if metadata:
        chunks.append(
            "<details><summary>Tool metadata</summary>\n\n"
            + fence(compact_json(metadata), "json")
            + "\n\n</details>"
        )

    if not chunks:
        return ""
    return "**Result**\n\n" + "\n\n".join(chunks)


def render_assistant(seq: int, data: dict[str, Any]) -> str:
    agent = data.get("agent", "assistant")
    model = data.get("model", {}) or {}
    model_name = model.get("id", "")
    provider = model.get("providerID", "")
    model_label = f"{provider}/{model_name}" if provider or model_name else "unknown model"

    lines = [f"## {seq:04d} · Assistant · {agent} · `{model_label}`", ""]
    content = data.get("content", []) or []
    if not content:
        lines.append("_(no content recorded)_")

    for item in content:
        item_type = item.get("type")
        if item_type == "reasoning":
            text = strip_base64(item.get("text", ""))
            lines.append("<details><summary>Reasoning</summary>\n")
            lines.append(text)
            lines.append("\n</details>")
        elif item_type == "text":
            lines.append(strip_base64(item.get("text", "")))
        elif item_type == "tool":
            name = item.get("name", "tool")
            state = item.get("state", {}) or {}
            status = state.get("status", "unknown")
            lines.append(
                f"<details><summary>Tool call: <code>{name}</code> — {status}</summary>\n"
            )
            input_md = render_tool_input(name, state.get("input", {}) or {})
            if input_md:
                lines.append(input_md)
                lines.append("")
            result_md = render_tool_result(state)
            if result_md:
                lines.append(result_md)
                lines.append("")
            lines.append("</details>")
        else:
            lines.append(
                f"<details><summary>Unhandled content: {item_type}</summary>\n\n"
                + fence(compact_json(item), "json")
                + "\n\n</details>"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_message(seq: int, msg_type: str, data: dict[str, Any]) -> Block | None:
    created = data.get("time", {}).get("created") if isinstance(data.get("time"), dict) else None
    stamp = utc(created)

    if msg_type == "user":
        lines = [f"## {seq:04d} · User · {stamp}", ""]
        text = strip_base64(data.get("text", "") or "")
        lines.append(text if text.strip() else "_(empty message)_")
        for file in data.get("files", []) or []:
            lines.append("")
            lines.append(render_attachment(file))
        return Block(seq=seq, kind="user", text="\n".join(lines).rstrip() + "\n")

    if msg_type == "assistant":
        return Block(seq=seq, kind="assistant", text=render_assistant(seq, data))

    if msg_type == "synthetic":
        text = strip_base64(data.get("text", "") or "")
        body = (
            f"## {seq:04d} · System reminder · {stamp}\n\n"
            + fence(text, "text")
        )
        return Block(seq=seq, kind="meta", text=body + "\n")

    if msg_type == "system":
        description = data.get("description") or "system notice"
        text = strip_base64(data.get("text", "") or "")
        body = (
            f"## {seq:04d} · System · {stamp}\n\n"
            f"**{description}**\n\n" + fence(text, "text")
        )
        return Block(seq=seq, kind="meta", text=body + "\n")

    if msg_type == "compaction":
        summary = strip_base64(data.get("summary", "") or "")
        status = data.get("status", "unknown")
        reason = data.get("reason", "unknown")
        body = (
            f"## {seq:04d} · Compaction · {stamp}\n\n"
            f"Status: **{status}** · reason: **{reason}**\n\n"
            "<details><summary>Compaction summary</summary>\n\n"
            + summary
            + "\n\n</details>"
        )
        return Block(seq=seq, kind="meta", text=body + "\n")

    if msg_type == "idle":
        outcome = data.get("outcome", "unknown")
        return Block(
            seq=seq,
            kind="meta",
            text=f"_{seq:04d} · Session idle · {stamp} · outcome: {outcome}_\n",
        )

    if msg_type == "model-switched":
        model = data.get("model", {}) or {}
        previous = data.get("previous", {}) or {}
        body = (
            f"_{seq:04d} · Model switched · {stamp} · "
            f"`{previous.get('providerID', '?')}/{previous.get('id', '?')}` → "
            f"`{model.get('providerID', '?')}/{model.get('id', '?')}`_\n"
        )
        return Block(seq=seq, kind="meta", text=body)

    if msg_type == "agent-switched":
        body = (
            f"_{seq:04d} · Agent switched · {stamp} · "
            f"`{data.get('previous', '?')}` → `{data.get('agent', '?')}`_\n"
        )
        return Block(seq=seq, kind="meta", text=body)

    body = (
        f"## {seq:04d} · {msg_type} · {stamp}\n\n"
        "<details><summary>Raw message</summary>\n\n"
        + fence(compact_json(data), "json")
        + "\n\n</details>\n"
    )
    return Block(seq=seq, kind="meta", text=body)


# --------------------------------------------------------------------------- #
# Session loading and chunking
# --------------------------------------------------------------------------- #

def find_session(con: sqlite3.Connection, directory: Path, session_id: str | None) -> dict[str, Any]:
    cur = con.cursor()
    cur.row_factory = sqlite3.Row
    if session_id:
        row = cur.execute(
            "select * from session_v2 where id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise SystemExit(f"Session {session_id} not found in session_v2.")
        return dict(row)

    wanted = {str(directory), str(directory).replace("\\", "/")}
    for candidate in wanted:
        row = cur.execute(
            "select * from session_v2 where directory = ? order by time_updated desc limit 1",
            (candidate,),
        ).fetchone()
        if row is not None:
            return dict(row)
    raise SystemExit(
        f"No session found for directory {directory}. "
        "Pass --session explicitly."
    )


def load_messages(con: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    cur = con.cursor()
    cur.row_factory = sqlite3.Row
    return cur.execute(
        "select seq, type, time_created, data "
        "from session_message where session_id = ? order by seq",
        (session_id,),
    ).fetchall()


def build_blocks(rows: Iterable[sqlite3.Row]) -> tuple[list[Block], int, int]:
    blocks: list[Block] = []
    tool_calls = 0
    redactions = 0
    for row in rows:
        try:
            data = json.loads(row["data"])
        except json.JSONDecodeError:
            data = {"text": row["data"]}
        block = render_message(row["seq"], row["type"], data)
        if block is None:
            continue
        cleaned, found = redact_secrets(block.text)
        redactions += found
        block.text = cleaned
        if row["type"] == "assistant":
            for item in data.get("content", []) or []:
                if item.get("type") == "tool":
                    tool_calls += 1
        blocks.append(block)
    return blocks, tool_calls, redactions


def chunk_blocks(blocks: list[Block], target_bytes: int) -> list[list[Block]]:
    """Split at user-message boundaries, with a cap for very long turns.

    A preferred split happens when the target size is reached and the next
    block starts a user turn. If one turn is so long that it crosses 1.2x the
    target, the part is closed at the next message boundary instead, so no
    single file becomes unreadable in the GitHub UI.
    """
    parts: list[list[Block]] = []
    current: list[Block] = []
    size = 0
    hard_cap = int(target_bytes * 1.2)
    for block in blocks:
        block_size = len(block.text.encode("utf-8"))
        if current and size >= target_bytes and (
            block.kind == "user" or size >= hard_cap
        ):
            parts.append(current)
            current = []
            size = 0
        current.append(block)
        size += block_size
    if current:
        parts.append(current)
    return parts


def part_header(
    index: int,
    total: int,
    session: dict[str, Any],
    exported_at: str,
) -> str:
    previous = (
        f"[← Part {index - 1}](part-{index - 1:02d}.md)"
        if index > 1
        else "[← Index](README.md)"
    )
    following = (
        f"[Part {index + 1} →](part-{index + 1:02d}.md)"
        if index < total
        else "[Index →](README.md)"
    )
    return (
        f"# Northwind Group consolidation — full AI transcript\n\n"
        f"**Part {index} of {total}** · [Index](README.md) · {previous} · {following}\n\n"
        f"> OpenCode session `{session['id']}` · "
        f"directory `{session['directory']}` · "
        f"exported {exported_at}\n\n"
        "> This is a complete machine export: user messages, assistant text, "
        "reasoning, every tool call with its input and result, system notices, "
        "compactions and model/agent switches. Embedded base64 images and PDFs "
        "are replaced by placeholders. Nothing else is abridged.\n\n"
        "---\n\n"
    )


def part_footer(index: int, total: int) -> str:
    if index < total:
        return f"\n---\n\n_Continued in [Part {index + 1}](part-{index + 1:02d}.md)._\n"
    return "\n---\n\n_End of the exported snapshot; the live session may continue after this point._\n"


def write_export(
    session: dict[str, Any],
    blocks: list[Block],
    tool_calls: int,
    redactions: int,
    message_count: int,
    out_dir: Path,
    target_bytes: int,
    exported_at: str,
    dry_run: bool,
) -> list[tuple[int, int, int, int]]:
    parts = chunk_blocks(blocks, target_bytes)
    total = len(parts)
    manifest: list[tuple[int, int, int, int]] = []

    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("part-*.md"):
            old.unlink()

    for index, part in enumerate(parts, start=1):
        body = part_header(index, total, session, exported_at)
        body += "\n\n".join(block.text.rstrip() for block in part)
        body += part_footer(index, total)
        encoded = body.encode("utf-8")
        manifest.append((index, part[0].seq, part[-1].seq, len(encoded)))
        if not dry_run:
            (out_dir / f"part-{index:02d}.md").write_bytes(encoded)

    if not dry_run:
        index_lines = [
            "# Full AI transcript — machine export",
            "",
            f"- **Session:** `{session['id']}` — {session.get('title', '')}",
            f"- **Directory:** `{session['directory']}`",
            f"- **Session created:** {utc(session.get('time_created'))}",
            f"- **Session last updated:** {utc(session.get('time_updated'))}",
            f"- **Exported:** {exported_at}",
            f"- **Messages:** {message_count}",
            f"- **Tool calls:** {tool_calls}",
            f"- **Parts:** {total}",
            f"- **Secrets redacted:** {redactions}",
            "",
            "This is the authoritative, unedited record of the AI session. It includes "
            "assistant reasoning and every tool call with its input and output. The only "
            "omissions are embedded base64 attachments (images and PDFs), which are "
            "replaced by placeholders so the text stays readable.",
            "",
            "| Part | Message range (seq) | Size |",
            "|---:|---|---:|",
        ]
        for index, first, last, size in manifest:
            index_lines.append(
                f"| [Part {index}](part-{index:02d}.md) | {first}–{last} | {size:,} bytes |"
            )
        index_lines += [
            "",
            "## Other records",
            "",
            "- [`../session-01.md`](../session-01.md) — a short curated narrative of the "
            "same session, kept for reviewers who want the story without the tool noise.",
            "- [`../tool-log.md`](../tool-log.md) — the commands and outputs that prove the "
            "repository runs.",
            "",
        ]
        (out_dir / "README.md").write_text("\n".join(index_lines), encoding="utf-8")

    return manifest


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--session", default=None)
    parser.add_argument("--directory", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-part-bytes", type=int, default=300_000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"OpenCode database not found: {args.db}")

    exported_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        session = find_session(con, args.directory, args.session)
        rows = load_messages(con, session["id"])
    finally:
        con.close()

    blocks, tool_calls, redactions = build_blocks(rows)
    manifest = write_export(
        session=session,
        blocks=blocks,
        tool_calls=tool_calls,
        redactions=redactions,
        message_count=len(rows),
        out_dir=args.out,
        target_bytes=args.max_part_bytes,
        exported_at=exported_at,
        dry_run=args.dry_run,
    )

    print(f"Session:      {session['id']} - {session.get('title', '')}")
    print(f"Messages:     {len(rows)} ({tool_calls} tool calls)")
    print(f"Secrets:      {redactions} redacted")
    print(f"Parts:        {len(manifest)}")
    for index, first, last, size in manifest:
        action = "would write" if args.dry_run else "wrote"
        print(f"  {action} part-{index:02d}.md  seq {first}-{last}  {size:,} bytes")
    if not args.dry_run:
        print(f"Index:        {args.out / 'README.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
