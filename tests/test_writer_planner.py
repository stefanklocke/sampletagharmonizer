from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from sampletagharmonizer.parsers.ni_metadata import NI_SOUNDINFO_MIME
from sampletagharmonizer.writer import plan_existing_id3_geob_update


def chunk(chunk_id: bytes, payload: bytes, pad: bool = True) -> bytes:
    data = chunk_id + len(payload).to_bytes(4, "little") + payload
    return data + (b"\x00" if pad and len(payload) % 2 else b"")


def wav_bytes(chunks: list[bytes]) -> bytes:
    body = b"WAVE" + b"".join(chunks)
    return b"RIFF" + len(body).to_bytes(4, "little") + body


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


class WriterPlannerTest(unittest.TestCase):
    def test_plans_existing_id3_geob_update(self) -> None:
        audio = b"\x01\x02\x03\x04"
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.wav"
            output = Path(tmp) / "output.wav"
            source.write_bytes(
                wav_bytes(
                    [
                        chunk(b"fmt ", fmt_payload()),
                        chunk(b"data", audio),
                        chunk(b"ID3 ", id3_payload([geob_frame(soundinfo_geob_data())])),
                    ]
                )
            )

            plan = plan_existing_id3_geob_update(source, output)

        self.assertEqual(plan.source_path, source)
        self.assertEqual(plan.output_path, output)
        self.assertEqual(plan.strategy, "preserve_audio_update_existing_id3_geob")
        self.assertEqual(plan.write_safety, "safe_to_update_existing_metadata")
        self.assertEqual(plan.coverage_safety, "safe_to_rewrite")
        self.assertEqual(plan.source_audio_sha256, hashlib.sha256(audio).hexdigest())
        self.assertEqual(plan.source_audio_size, len(audio))
        self.assertEqual(
            [item.id for item in plan.copy_ranges],
            ["copy_before_target_geob_frame", "copy_after_target_geob_frame"],
        )
        self.assertEqual(plan.copy_ranges[0].end, plan.replace_ranges[0].start)
        self.assertEqual(plan.copy_ranges[1].start, plan.replace_ranges[0].end)
        self.assertEqual([item.id for item in plan.replace_ranges], ["replace_target_geob_frame"])
        self.assertIn("immutable_audio_data_payload", [item.id for item in plan.immutable_ranges])
        self.assertEqual(plan.immutable_ranges[0].metadata["sha256"], hashlib.sha256(audio).hexdigest())
        self.assertEqual(
            [field.id for field in plan.patch_fields],
            [
                "riff_size",
                "id3_chunk_payload_size",
                "id3_tag_size",
                "geob_frame_payload_size",
            ],
        )
        self.assertEqual(plan.normalizations, [])
        self.assertTrue(all(plan.preconditions.values()))

    def test_rejects_file_without_id3_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.wav"
            source.write_bytes(
                wav_bytes(
                    [
                        chunk(b"fmt ", fmt_payload()),
                        chunk(b"data", b"\x01\x02\x03\x04"),
                    ]
                )
            )

            with self.assertRaisesRegex(ValueError, "missing_id3_chunk"):
                plan_existing_id3_geob_update(source, Path(tmp) / "output.wav")

    def test_rejects_multiple_soundinfo_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.wav"
            source.write_bytes(
                wav_bytes(
                    [
                        chunk(b"fmt ", fmt_payload()),
                        chunk(b"data", b"\x01\x02\x03\x04"),
                        chunk(
                            b"ID3 ",
                            id3_payload(
                                [
                                    geob_frame(soundinfo_geob_data()),
                                    geob_frame(soundinfo_geob_data()),
                                ]
                            ),
                        ),
                    ]
                )
            )

            with self.assertRaisesRegex(ValueError, "multiple_ni_soundinfo_payloads"):
                plan_existing_id3_geob_update(source, Path(tmp) / "output.wav")


if __name__ == "__main__":
    unittest.main()
