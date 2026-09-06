"""Loads the one-pagers the bot answers from.

Drop a .md file per project into knowledge/ (valhalla.md, olympus.md, ...).
Every file is concatenated into the system prompt, so keep them tight - this
text is sent on every single question.
"""

from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


def load_knowledge() -> str:
    if not KNOWLEDGE_DIR.is_dir():
        return ""

    sections = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            sections.append(f"# {path.stem.upper()}\n\n{text}")

    return "\n\n---\n\n".join(sections)
