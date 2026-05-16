from __future__ import annotations

import unittest

from sampletagharmonizer.parsers.ni_metadata import (
    NI_SOUNDINFO_MIME,
    GeobFrameMetadata,
    NiSoundInfoSummary,
    parse_geob_frame,
    summarize_soundinfo_texts,
)


def encoded_string(text: str) -> bytes:
    return len(text).to_bytes(4, "little") + text.encode("utf-16le")


class NiMetadataTest(unittest.TestCase):
    def test_summarizes_soundinfo_texts_as_typed_value(self) -> None:
        summary = summarize_soundinfo_texts(
            [
                "Kick Tight",
                "Native Instruments",
                "Maschine Factory Library",
                "\\:Drums\\:Kick",
                "\\@Color",
                "Bright",
            ]
        )

        self.assertIsInstance(summary, NiSoundInfoSummary)
        self.assertEqual(summary.title, "Kick Tight")
        self.assertEqual(summary.vendor, "Native Instruments")
        self.assertEqual(summary.product, "Maschine Factory Library")
        self.assertEqual(summary.category_paths, [["Drums", "Kick"]])
        self.assertEqual(summary.attributes, {"Color": "Bright"})

    def test_parses_geob_frame_as_typed_metadata(self) -> None:
        data = b"".join(
            [
                b"\x00",
                b"application/octet-stream\x00",
                NI_SOUNDINFO_MIME.encode("latin-1"),
                b"\x00",
                encoded_string("Snare Dusty"),
                encoded_string("Native Instruments"),
                encoded_string("\\:Drums\\:Snare"),
            ]
        )

        metadata = parse_geob_frame(data)

        self.assertIsInstance(metadata, GeobFrameMetadata)
        assert metadata is not None
        self.assertEqual(metadata.encoding, 0)
        self.assertEqual(metadata.object_id, NI_SOUNDINFO_MIME)
        self.assertEqual(metadata.summary.title, "Snare Dusty")
        self.assertEqual(metadata.summary.category_paths, [["Drums", "Snare"]])
        self.assertEqual(metadata.to_dict()["summary"]["title"], "Snare Dusty")


if __name__ == "__main__":
    unittest.main()
