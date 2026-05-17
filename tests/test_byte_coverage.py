from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sampletagharmonizer.byte_coverage import build_wav_byte_map
from sampletagharmonizer.parsers.ni_metadata import NI_SOUNDINFO_MIME


def chunk(chunk_id: bytes, payload: bytes, pad: bool = True) -> bytes:
    data = chunk_id + len(payload).to_bytes(4, "little") + payload
    return data + (b"\x00" if pad and len(payload) % 2 else b"")


def wav_bytes(chunks: list[bytes], riff_size_delta: int = 0) -> bytes:
    body = b"WAVE" + b"".join(chunks)
    riff_size = len(body) + riff_size_delta
    return b"RIFF" + riff_size.to_bytes(4, "little") + body


def fmt_payload() -> bytes:
    return b"".join(
        [
            (1).to_bytes(2, "little"),
            (1).to_bytes(2, "little"),
            (44_100).to_bytes(4, "little"),
            (88_200).to_bytes(4, "little"),
            (2).to_bytes(2, "little"),
            (16).to_bytes(2, "little"),
        ]
    )


def synchsafe(value: int) -> bytes:
    return bytes(
        [
            (value >> 21) & 0x7F,
            (value >> 14) & 0x7F,
            (value >> 7) & 0x7F,
            value & 0x7F,
        ]
    )


def encoded_string(text: str) -> bytes:
    return len(text).to_bytes(4, "little") + text.encode("utf-16le")


def id3_payload(frames: list[bytes]) -> bytes:
    body = b"".join(frames)
    return b"ID3\x04\x00\x00" + synchsafe(len(body)) + body


def geob_frame(data: bytes) -> bytes:
    return b"GEOB" + len(data).to_bytes(4, "big") + b"\x00\x00" + data


def soundinfo_geob_data() -> bytes:
    return b"".join(
        [
            b"\x00\x00",
            NI_SOUNDINFO_MIME.encode("latin-1"),
            b"\x00",
            encoded_string("Kick Tight"),
            encoded_string("\\:Drums\\:Kick"),
        ]
    )


def msgpack_ni_tag_object() -> bytes:
    return b"".join(
        [
            b"\x82",
            b"\xa4name",
            b"\xa4Kick",
            b"\xa6vendor",
            b"\xb2Native Instruments",
        ]
    )


class ByteCoverageTest(unittest.TestCase):
    def build_map(self, data: bytes):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.wav"
            path.write_bytes(data)
            return build_wav_byte_map(path)

    def test_maps_standard_wav_without_diagnostics(self) -> None:
        coverage = self.build_map(
            wav_bytes(
                [
                    chunk(b"fmt ", fmt_payload()),
                    chunk(b"data", b"\x01\x02\x03\x04"),
                ]
            )
        )

        self.assertEqual(coverage.safety, "safe_to_rewrite")
        self.assertEqual(coverage.diagnostics, [])
        self.assertEqual(
            [(region.kind, region.start, region.end) for region in coverage.regions],
            [
                ("container_header", 0, 12),
                ("chunk_header", 12, 20),
                ("chunk_payload", 20, 36),
                ("chunk_header", 36, 44),
                ("audio", 44, 48),
            ],
        )

    def test_maps_odd_chunk_padding(self) -> None:
        coverage = self.build_map(
            wav_bytes(
                [
                    chunk(b"fmt ", fmt_payload()),
                    chunk(b"data", b"\x01\x02\x03"),
                    chunk(b"ID3 ", id3_payload([geob_frame(soundinfo_geob_data())])),
                ]
            )
        )

        padding_regions = [region for region in coverage.regions if region.kind == "padding"]

        self.assertEqual(coverage.safety, "safe_to_rewrite")
        self.assertIn((47, 48), [(region.start, region.end) for region in padding_regions])

    def test_reports_missing_padding_before_valid_chunk(self) -> None:
        coverage = self.build_map(
            wav_bytes(
                [
                    chunk(b"fmt ", fmt_payload()),
                    chunk(b"data", b"\x01\x02\x03", pad=False),
                    chunk(b"ID3 ", id3_payload([geob_frame(soundinfo_geob_data())])),
                ]
            )
        )

        self.assertEqual(coverage.safety, "safe_with_known_tolerances")
        self.assertIn("missing_chunk_padding", {diagnostic.code for diagnostic in coverage.diagnostics})

    def test_reports_extra_zero_padding_before_valid_chunk(self) -> None:
        coverage = self.build_map(
            wav_bytes(
                [
                    chunk(b"fmt ", fmt_payload()),
                    chunk(b"data", b"\x01\x02\x03", pad=False),
                    b"\x00" * 4,
                    chunk(b"ID3 ", id3_payload([geob_frame(soundinfo_geob_data())])),
                ]
            )
        )

        self.assertEqual(coverage.safety, "safe_with_known_tolerances")
        self.assertIn("extra_zero_padding_before_chunk", {diagnostic.code for diagnostic in coverage.diagnostics})
        self.assertTrue(any(region.label == "Extra zero padding before chunk" for region in coverage.regions))

    def test_reports_truncated_chunk_payload(self) -> None:
        data = wav_bytes([chunk(b"fmt ", fmt_payload()), b"data" + (8).to_bytes(4, "little") + b"\x01\x02"])
        coverage = self.build_map(data)

        self.assertEqual(coverage.safety, "invalid")
        self.assertIn("truncated_chunk_payload", {diagnostic.code for diagnostic in coverage.diagnostics})

    def test_maps_nested_id3_geob_soundinfo_regions(self) -> None:
        coverage = self.build_map(
            wav_bytes(
                [
                    chunk(b"fmt ", fmt_payload()),
                    chunk(b"data", b"\x01\x02\x03\x04"),
                    chunk(b"ID3 ", id3_payload([geob_frame(soundinfo_geob_data())])),
                ]
            )
        )
        kinds = {region.kind for region in coverage.regions}
        strings = [
            region
            for region in coverage.regions
            if region.kind == "utf16le_length_prefixed_string"
        ]

        self.assertEqual(coverage.safety, "safe_to_rewrite")
        self.assertIn("id3_header", kinds)
        self.assertIn("id3_frame_header", kinds)
        self.assertIn("id3_frame_payload", kinds)
        self.assertIn("geob_encoding", kinds)
        self.assertIn("geob_mime", kinds)
        self.assertIn("ni_soundinfo_marker", kinds)
        self.assertIn("ni_soundinfo_payload", kinds)
        self.assertEqual([region.metadata["text"] for region in strings], ["Kick Tight", "\\:Drums\\:Kick"])

    def test_maps_msgpack_candidate_inside_geob_payload(self) -> None:
        geob_data = b"\x00\x00" + NI_SOUNDINFO_MIME.encode("latin-1") + b"\x00" + msgpack_ni_tag_object()
        coverage = self.build_map(
            wav_bytes(
                [
                    chunk(b"fmt ", fmt_payload()),
                    chunk(b"data", b"\x01\x02\x03\x04"),
                    chunk(b"ID3 ", id3_payload([geob_frame(geob_data)])),
                ]
            )
        )
        candidates = [region for region in coverage.regions if region.kind == "msgpack_candidate"]

        self.assertEqual(coverage.safety, "safe_to_rewrite")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].metadata["keys"], ["name", "vendor"])


if __name__ == "__main__":
    unittest.main()
