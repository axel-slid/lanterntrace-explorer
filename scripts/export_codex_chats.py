#!/usr/bin/env python3
"""Export the LanternTrace portions of local Codex sessions as public Markdown.

The export deliberately includes only user/assistant dialogue. System and developer
instructions, tool calls, tool outputs, environment blocks, and internal goal state
are excluded. Local home and temporary-image paths are normalized before writing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


HOME = Path.home()
SESSIONS = HOME / ".codex" / "sessions"
OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "codex-chats"


@dataclass(frozen=True)
class Export:
    filename: str
    title: str
    source: str
    start: str | None = None
    stop: str | None = None
    note: str | None = None


EXPORTS = [
    Export(
        "2026-08-01-initial-app-build.md",
        "Initial LanternTrace app build",
        "2026/08/01/rollout-2026-08-01T00-01-22-019fbc20-a0aa-7183-9310-5e3166bcb2ea.jsonl",
        start="ok whatever can you make a tool",
        note="The earlier portion of this mixed session concerned a different project and is excluded.",
    ),
    Export(
        "2026-08-09-modeling-validation-and-paper.md",
        "Modeling, validation, paper, and release work",
        "2026/08/09/rollout-2026-08-09T12-21-01-019fe7f8-aa11-7c20-9c79-ba07f57b70cb.jsonl",
        start="do you see the app that i made, lanterntrace explorer?",
    ),
    Export(
        "2026-08-09-reviewer-1.md",
        "Independent reviewer 1",
        "2026/08/09/rollout-2026-08-09T16-42-41-019fe8e8-396d-7e23-a6a3-56e6f3cdb4fe.jsonl",
    ),
    Export(
        "2026-08-09-reviewer-2.md",
        "Independent reviewer 2",
        "2026/08/09/rollout-2026-08-09T16-42-46-019fe8e8-4d49-7230-a64f-8dc4b8ac77a5.jsonl",
    ),
    Export(
        "2026-08-09-reviewer-3.md",
        "Independent reviewer 3",
        "2026/08/09/rollout-2026-08-09T16-42-52-019fe8e8-656f-7541-94a0-37d4e7bbcc7d.jsonl",
    ),
    Export(
        "2026-08-09-reviewer-4.md",
        "Independent reviewer 4",
        "2026/08/09/rollout-2026-08-09T16-46-33-019fe8eb-c458-7af3-96de-c3e23c8db10a.jsonl",
    ),
    Export(
        "2026-08-10-release-review-1.md",
        "Release usability review 1",
        "2026/08/10/rollout-2026-08-10T05-49-11-019febb8-4cbf-7940-b2c1-d44f227718f1.jsonl",
    ),
    Export(
        "2026-08-10-release-review-2.md",
        "Release usability review 2",
        "2026/08/10/rollout-2026-08-10T05-59-53-019febc2-1662-7600-86d7-28464e0dcc6e.jsonl",
    ),
    Export(
        "2026-08-11-lay-explainer.md",
        "Lay explainer work",
        "2026/08/11/rollout-2026-08-11T09-50-24-019ff1bb-7f40-7b20-928b-ac4857cafb73.jsonl",
        start="do you see the lanterfly lanterntrace project and the paper?",
        stop="somewhere in stanford i think i have a ct pet tool",
        note="The later portion of this mixed session concerned a medical-imaging app and is excluded.",
    ),
    Export(
        "2026-08-12-paper-rewrite.md",
        "Research-paper rewrite",
        "2026/08/12/rollout-2026-08-12T10-15-42-019ff6f9-032f-7550-abef-77d2a4575b9b.jsonl",
    ),
    Export(
        "2026-08-14-app-explanation-and-release.md",
        "App explanation and GitHub release",
        "2026/08/14/rollout-2026-08-14T10-11-26-01a00141-d418-74c0-9944-b8a9dc948880.jsonl",
        start="pull up this application",
        note="The earlier portion of this mixed session concerned OpenLeaf and is excluded.",
    ),
]


IGNORED_PREFIXES = (
    "<environment_context>",
    "<codex_internal_context",
    "<recommended_plugins>",
    "<subagent_notification>",
    "<turn_aborted>",
)


def content_text(content: list[dict]) -> str:
    pieces: list[str] = []
    for part in content:
        if part.get("type") in {"input_text", "output_text"}:
            pieces.append(part.get("text", ""))
        elif part.get("type") in {"input_image", "image"}:
            pieces.append("[Image attachment omitted from the text export]")
    return "\n\n".join(piece for piece in pieces if piece).strip()


def clean(text: str) -> str:
    text = re.sub(r"<image\b[^>]*>", "[Image attachment omitted from the text export]", text)
    text = text.replace("</image>", "")
    text = re.sub(
        r"(?:\[Image attachment omitted from the text export\]\s*){2,}",
        "[Image attachment omitted from the text export]\n\n",
        text,
    )
    text = text.replace(str(HOME), "$HOME")
    text = re.sub(r"/var/folders/\S+", "[temporary image path]", text)
    text = re.sub(r":codex-file-citation\{path=\"([^\"]+)\"[^}]*\}", r"`\1`", text)
    return text.strip()


def messages(path: Path) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            payload = row.get("payload", {})
            if row.get("type") != "response_item" or payload.get("type") != "message":
                continue
            role = payload.get("role")
            if role not in {"user", "assistant"}:
                continue
            text = content_text(payload.get("content", []))
            if not text or text.startswith(IGNORED_PREFIXES):
                continue
            result.append((role, clean(text)))
    return result


def select_segment(items: list[tuple[str, str]], export: Export) -> list[tuple[str, str]]:
    start = 0
    end = len(items)
    if export.start:
        needle = export.start.lower()
        start = next(i for i, (_, text) in enumerate(items) if needle in text.lower())
    if export.stop:
        needle = export.stop.lower()
        end = next(i for i, (_, text) in enumerate(items[start:], start) if needle in text.lower())
    return items[start:end]


def render(export: Export, items: list[tuple[str, str]]) -> str:
    lines = [
        f"# {export.title}",
        "",
        "Public dialogue export from a local Codex session. Only user-visible user/assistant messages are included.",
        "Hidden instructions, internal reasoning, environment metadata, tool calls, and tool output are intentionally excluded.",
    ]
    if export.note:
        lines.extend(["", export.note])
    for role, text in items:
        lines.extend(["", f"## {'User' if role == 'user' else 'Codex'}", "", text])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    written: list[tuple[Export, int]] = []
    for export in EXPORTS:
        source = SESSIONS / export.source
        selected = select_segment(messages(source), export)
        (OUTPUT / export.filename).write_text(render(export, selected), encoding="utf-8")
        written.append((export, len(selected)))

    index = [
        "# Codex conversation archive",
        "",
        "These transcripts document LanternTrace's design, model development, validation, writing, review, and release work.",
        "They are curated public-dialogue exports: system/developer instructions, hidden reasoning, environment metadata,",
        "tool calls, tool output, unrelated portions of mixed sessions, and temporary image files are not published.",
        "Local home-directory paths are normalized to `$HOME`.",
        "",
        "The exporter is [`scripts/export_codex_chats.py`](../../scripts/export_codex_chats.py).",
        "",
        "## Transcripts",
        "",
    ]
    for export, count in written:
        index.append(f"- [{export.title}]({export.filename}) — {count} dialogue messages")
    index.append("")
    (OUTPUT / "README.md").write_text("\n".join(index), encoding="utf-8")


if __name__ == "__main__":
    main()
