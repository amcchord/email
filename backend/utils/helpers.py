import re
from email.utils import parseaddr
from typing import Optional


def parse_email_address(raw: str) -> dict:
    name, addr = parseaddr(raw)
    return {"name": name, "address": addr}


def parse_email_list(raw: str) -> list[dict]:
    if not raw:
        return []
    parts = re.split(r",\s*", raw)
    return [parse_email_address(p.strip()) for p in parts if p.strip()]


def truncate_text(text: str, max_length: int = 200) -> str:
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length].rsplit(" ", 1)[0] + "..."


def sanitize_html(html: str) -> str:
    """Basic HTML sanitization - strips script tags."""
    if not html:
        return ""
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"on\w+\s*=\s*['\"][^'\"]*['\"]", "", html, flags=re.IGNORECASE)
    return html


def format_file_size(size_bytes: Optional[int]) -> str:
    if size_bytes is None or size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    unit_index = 0
    size = float(size_bytes)
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    return f"{size:.1f} {units[unit_index]}"
