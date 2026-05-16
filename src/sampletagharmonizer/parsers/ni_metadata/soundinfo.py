from __future__ import annotations

from .models import GeobFrameMetadata, LengthPrefixedString, NiSoundInfoSummary

NI_SOUNDINFO_MIME = "com.native-instruments.nisound.soundinfo"


def parse_geob_frame(data: bytes) -> GeobFrameMetadata | None:
    if not data:
        return None
    encoding = data[0]
    mime_end = data.find(b"\x00", 1)
    if mime_end < 0:
        return None

    mime = data[1:mime_end].decode("latin-1", errors="replace")
    payload = data[mime_end + 1 :]
    object_id = None
    metadata_payload = payload
    ni_marker = NI_SOUNDINFO_MIME.encode("latin-1") + b"\x00"
    ni_marker_offset = data.find(ni_marker)
    if ni_marker_offset >= 0:
        object_id = NI_SOUNDINFO_MIME
        metadata_payload = data[ni_marker_offset + len(ni_marker) :]

    utf16le_strings = scan_utf16le_length_prefixed_strings(metadata_payload)
    texts = [item.text for item in utf16le_strings]
    return GeobFrameMetadata(
        encoding=encoding,
        mime=mime,
        object_id=object_id,
        payload_size=len(payload),
        summary=summarize_soundinfo_texts(texts),
        utf16le_strings=utf16le_strings,
    )


def summarize_soundinfo_texts(texts: list[str]) -> NiSoundInfoSummary:
    category_paths = [
        [part for part in text.split("\\:") if part]
        for text in texts
        if text.startswith("\\:")
    ]
    attributes: dict[str, str | None] = {}
    for index, text in enumerate(texts):
        if not text.startswith("\\@"):
            continue
        key = text[2:]
        next_text = texts[index + 1] if index + 1 < len(texts) else None
        attributes[key] = next_text if next_text and not next_text.startswith("\\") else None

    regular_texts = [
        text
        for text in texts
        if not text.startswith("\\") and not text.isdecimal()
    ]
    product = next(
        (
            text
            for text in regular_texts[1:]
            if text != "Native Instruments" and not text.startswith("1.")
        ),
        None,
    )

    return NiSoundInfoSummary(
        title=regular_texts[0] if regular_texts else None,
        vendor="Native Instruments" if "Native Instruments" in regular_texts else None,
        product=product,
        category_paths=category_paths,
        attributes=attributes,
    )


def scan_utf16le_length_prefixed_strings(data: bytes) -> list[LengthPrefixedString]:
    strings: list[LengthPrefixedString] = []
    for offset in range(max(0, len(data) - 4)):
        length = int.from_bytes(data[offset : offset + 4], "little")
        byte_length = length * 2
        start = offset + 4
        end = start + byte_length
        if length < 1 or length > 200 or end > len(data):
            continue
        raw = data[start:end]
        if any(raw[index + 1] != 0 for index in range(0, len(raw), 2)):
            continue
        text = raw.decode("utf-16le", errors="replace")
        if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
            continue
        printable = sum(1 for char in text if char.isprintable())
        if printable < max(1, int(len(text) * 0.8)):
            continue
        strings.append(LengthPrefixedString(offset=offset, length=length, text=text))
    return strings
