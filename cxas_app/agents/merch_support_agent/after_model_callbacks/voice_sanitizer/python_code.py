# >>> BEGIN SHARED voice_sanitizer: generated from lib/shared_python/voice_sanitizer.py by scripts/bundle_shared_imports.py. Edit the lib/ file, not this copy. <<<
# Shared voice-output sanitizer: the after_model_callback of every Totto agent.
# CXAS runs each agent's callbacks as separate self-contained files, so
# scripts/bundle_shared_imports.py copies this fragment verbatim into
# agents/<agent>/after_model_callbacks/voice_sanitizer/python_code.py for all four agents.
#
# It is a deterministic safety net behind the voice guidelines in global_instruction.txt:
# markdown, emoji and "https://" prefixes are stripped from the visible text parts of a
# model response before text-to-speech reads them. Tool calls, thought parts and audio are
# never touched. When nothing needs cleaning, or anything unexpected happens, it returns
# None so the platform keeps the original response.
# CallbackContext, LlmResponse and Part are platform globals and are not imported.

import re
from typing import Optional

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\u2B50\u2B55\u231A\u231B\u23E9-\u23FA\uFE0F\u200D]"
)
_MD_LINK = re.compile(r"\[([^\]\n]+)\]\(\s*([^)\s]+)\s*\)")
_URL_PREFIX = re.compile(r"\bhttps?://(?:www\.)?|\bwww\.", re.IGNORECASE)
_DOMAIN_TRAILING_SLASH = re.compile(r"(\.[a-z]{2,6})/(?=[\s.,;:!?)]|$)", re.IGNORECASE)
_CODE_FENCE = re.compile(r"```[a-zA-Z]*")
_INLINE_CODE = re.compile(r"`([^`\n]*)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_HEADING = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+")
_BULLET = re.compile(r"(?m)^[ \t]*[*\-\u2022][ \t]+")
_NUMBERED = re.compile(r"(?m)^[ \t]*\d{1,2}[.)][ \t]+")
_HASH_NUMBER = re.compile(r"#(?=\d)")
_ARROW = re.compile(r"[ \t]*(?:->|=>|\u2192)[ \t]*")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")


def _domain_of(url: str) -> str:
    domain = _URL_PREFIX.sub("", url.strip())
    return domain[:-1] if domain.endswith("/") else domain


def clean_spoken_text(text: str) -> str:
    """Returns text with markdown, emoji, URL prefixes and list markers removed."""

    def _link(match: "re.Match[str]") -> str:
        label, domain = match.group(1).strip(), _domain_of(match.group(2))
        if not domain or domain.lower() in label.lower():
            return label
        return f"{label} ({domain})"

    out = _MD_LINK.sub(_link, text)
    out = _URL_PREFIX.sub("", out)
    out = _DOMAIN_TRAILING_SLASH.sub(r"\1", out)
    out = _CODE_FENCE.sub("", out)
    out = _INLINE_CODE.sub(r"\1", out)
    out = _BOLD.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(2), out)
    out = _HEADING.sub("", out)
    out = _BULLET.sub("", out)
    out = _NUMBERED.sub("", out)
    out = out.replace("*", "")
    out = _HASH_NUMBER.sub("", out)
    out = _ARROW.sub(" - ", out)
    out = _EMOJI.sub("", out)
    out = _MULTI_SPACE.sub(" ", out)
    lines = [line.strip() for line in out.split("\n")]
    return "\n".join(lines).strip()


def after_model_callback(callback_context: CallbackContext, llm_response: LlmResponse) -> Optional[LlmResponse]:
    try:
        content = getattr(llm_response, "content", None)
        parts = list(getattr(content, "parts", None) or [])
        new_parts = []
        changed = False
        for part in parts:
            text = getattr(part, "text", None)
            if isinstance(text, str) and text and not getattr(part, "thought", False):
                cleaned = clean_spoken_text(text)
                if cleaned != text:
                    changed = True
                    if cleaned:
                        new_parts.append(Part.from_text(text=cleaned))
                    continue
            new_parts.append(part)
        if not changed:
            return None
        cleaned_response = LlmResponse.from_parts(parts=new_parts)
        for flag in ("partial", "turn_complete"):
            value = getattr(llm_response, flag, None)
            if value is None:
                continue
            try:
                setattr(cleaned_response, flag, value)
            except (AttributeError, TypeError, ValueError):
                pass  # Streaming flags are best-effort; the cleaned text still applies.
        return cleaned_response
    except Exception as exc:  # Fail open: never break a turn because of the safety net.
        print(f"voice_sanitizer: left response unchanged after {type(exc).__name__}: {exc}")
        return None
# >>> END SHARED voice_sanitizer <<<
