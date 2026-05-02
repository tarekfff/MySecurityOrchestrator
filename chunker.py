"""
Convert raw PDF sections into atomic, metadata-rich chunks ready for embedding.

Each chunk carries:
  - topic  : normalised vulnerability/topic name  (e.g. "xss")
  - type   : semantic role of the text            (e.g. "mitigation")
  - content: the text itself
  - tags   : additional keyword labels
  - source : "WAHH" (Web App Hacker's Handbook)
  - page_start / page_end
"""

from __future__ import annotations

import hashlib
import re
import textwrap
from dataclasses import dataclass, field
from typing import Optional

from pdf_extractor import Section


# ── Topic taxonomy ─────────────────────────────────────────────────────────────
#
# Each entry: canonical_name → list of keyword signals (matched against the
# heading + first 200 chars of content, case-insensitive).

TOPIC_SIGNALS: dict[str, list[str]] = {
    "xss": [
        "cross-site scripting", "xss", "script injection",
        "reflected xss", "stored xss", "dom-based xss",
    ],
    "sql_injection": [
        "sql injection", "sqli", "blind sql", "database injection",
        "union select", "error-based", "time-based blind",
    ],
    "csrf": [
        "cross-site request forgery", "csrf", "xsrf", "anti-csrf",
    ],
    "rce": [
        "remote code execution", "rce", "arbitrary code",
        "os command injection", "command injection", "shell injection",
    ],
    "path_traversal": [
        "path traversal", "directory traversal", "local file inclusion",
        "lfi", "remote file inclusion", "rfi", "dot-dot-slash", "../",
    ],
    "authentication": [
        "authentication", "login mechanism", "brute force", "password guessing",
        "credential", "multifactor", "mfa", "2fa", "ssh login", "login failure",
    ],
    "brute_force": [
        "brute force", "password guessing", "dictionary attack", "credential stuffing",
        "authentication failure", "login attempt", "ssh brute",
    ],
    "phishing": [
        "phishing", "malicious email", "spearphishing", "email attachment",
        "social engineering", "credential harvesting",
    ],
    "ransomware": [
        "ransomware", "encryption attack", "mass encryption", "shadow copy",
        "cryptolocker", "data kidnapping",
    ],
    "data_breach": [
        "data breach", "data exfiltration", "information disclosure",
        "sensitive data leakage", "database leak", "unauthorized access",
    ],
    "ddos": [
        "ddos", "denial of service", "syn flood", "network flood",
        "traffic spike", "availability attack",
    ],
    "session_management": [
        "session management", "session token", "cookie security",
        "session fixation", "session hijacking", "jwt",
    ],
    "access_control": [
        "access control", "authorization", "privilege escalation",
        "insecure direct object reference", "idor", "broken access",
    ],
    "xxe": [
        "xml external entity", "xxe", "xml injection", "dtd",
    ],
    "ssrf": [
        "server-side request forgery", "ssrf",
    ],
    "clickjacking": [
        "clickjacking", "ui redressing", "iframe overlay",
    ],
    "open_redirect": [
        "open redirect", "unvalidated redirect", "url redirection",
    ],
    "file_upload": [
        "file upload", "unrestricted upload", "malicious file upload",
    ],
    "deserialization": [
        "deserialization", "insecure deserialization", "object injection",
    ],
    "business_logic": [
        "business logic", "logic flaw", "workflow bypass", "price manipulation",
    ],
    "http_headers": [
        "security header", "content security policy", "csp", "hsts",
        "x-frame-options", "cors misconfiguration",
    ],
    "information_disclosure": [
        "information disclosure", "error message", "stack trace",
        "verbose error", "source code disclosure",
    ],
}

# ── Chunk-type taxonomy ────────────────────────────────────────────────────────
#
# Matched against the section heading (case-insensitive).
# Order matters: first match wins.

TYPE_PATTERNS: list[tuple[str, list[str]]] = [
    ("mitigation",    ["prevent", "mitigat", "defense", "protect", "countermeasure",
                       "fix", "remediat", "sanitiz", "whitelist", "patch", "secure"]),
    ("exploitation",  ["exploit", "attack", "payload", "bypass", "inject", "execute",
                       "leverag", "craft", "weaponiz"]),
    ("detection",     ["detect", "find", "test", "identif", "scan", "discover",
                       "recogni", "spot", "check for"]),
    ("symptoms",      ["sign", "symptom", "indicator", "evidence", "artifact",
                       "manifest", "behav"]),
    ("introduction",  ["what is", "overview", "introduc", "definition", "background",
                       "concept", "occurs when", "allow"]),
]

FALLBACK_TYPE = "general"


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    chunk_id:   str
    topic:      str
    type:       str
    content:    str
    tags:       list[str]
    source:     str
    page_start: int
    page_end:   int


# ── Helpers ────────────────────────────────────────────────────────────────────

def _detect_topic(heading: str, content: str) -> Optional[str]:
    haystack = (heading + " " + content[:300]).lower()
    for topic, signals in TOPIC_SIGNALS.items():
        if any(sig in haystack for sig in signals):
            return topic
    return None


def _detect_type(heading: str) -> str:
    h = heading.lower()
    for chunk_type, signals in TYPE_PATTERNS:
        if any(sig in h for sig in signals):
            return chunk_type
    return FALLBACK_TYPE


def _split_into_word_windows(text: str, max_words: int, min_words: int) -> list[str]:
    """
    Split text into overlapping windows of ~max_words words.
    Overlap = 20 % of max_words so context is preserved across chunk boundaries.
    """
    words = text.split()
    if len(words) <= max_words:
        return [text] if len(words) >= min_words else []

    step = max(1, int(max_words * 0.80))
    windows: list[str] = []
    start = 0
    while start < len(words):
        window = words[start : start + max_words]
        if len(window) >= min_words:
            windows.append(" ".join(window))
        start += step
    return windows


# ── Public API ─────────────────────────────────────────────────────────────────

def section_to_chunks(
    section: Section,
    max_words: int = 250,
    min_words: int = 50,
    source: str = "WAHH",
) -> list[Chunk]:
    topic = _detect_topic(section.heading, section.content)
    if topic is None:
        return []

    chunk_type = _detect_type(section.heading)
    windows = _split_into_word_windows(section.content, max_words, min_words)
    if not windows:
        return []

    tags = [topic, chunk_type]
    chunks: list[Chunk] = []
    for idx, window in enumerate(windows):
        content_hash = hashlib.md5(window.encode()).hexdigest()[:8]
        chunk_id = f"{topic}_{chunk_type}_{section.page_start}_{idx:03d}_{content_hash}"
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                topic=topic,
                type=chunk_type,
                content=window,
                tags=tags,
                source=source,
                page_start=section.page_start,
                page_end=section.page_end,
            )
        )
    return chunks


def sections_to_chunks(
    sections: list[Section],
    max_words: int = 250,
    min_words: int = 50,
) -> list[Chunk]:
    result: list[Chunk] = []
    for section in sections:
        result.extend(section_to_chunks(section, max_words, min_words))
    return result
