from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from sampletagharmonizer.parsers.wav import inspect_audio_identity, iter_riff_chunks


def chunk(chunk_id: bytes, payload: bytes, pad: bool = True) -> bytes:
    data = chunk_id + len(payload).to_bytes(4, "little") + payload
    if pad and len(payload) % 2:
        data += b"\x00"
    return data


def wav_bytes(chunks: list[bytes], riff_size_delta: int = 0) -> bytes:
    body = b"WAVE" + b"".join(chunks)
    riff_size = len(body) + riff_size_delta
    return b"RIFF" + riff_size.to_bytes(4, "little") + body


def fmt_payload(channels: int = 1, sample_rate: int = 44_100, bits_per_sample: int = 16) -> bytes:
    block_align = channels * bits_per_sample // 8
    byte_rate = sample_rate * block_align
    return b"".join(
        [
            (1).to_bytes(2, "little"),
            channels.to_bytes(2, "little"),
            sample_rate.to_bytes(4, "little"),
            byte_rate.to_bytes(4, "little"),
            block_align.to_bytes(2, "little"),
            bits_per_sample.to_bytes(2, "little"),
        ]
    )


class WavParserTest(unittest.TestCase):
    def parse_temp(self, data: bytes):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.wav"
            path.write_bytes(data)
            return inspect_audio_identity(path), [(c.chunk_id, c.offset, c.size) for c in iter_riff_chunks(path)]

    def test_reads_standard_wav_identity(self) -> None:
        audio = b"\x01\x02\x03\x04"
        identity, chunks = self.parse_temp(
            wav_bytes(
                [
                    chunk(b"fmt ", fmt_payload(channels=2, bits_per_sample=16)),
                    chunk(b"data", audio),
                ]
            )
        )

        self.assertEqual(identity.data_sha256, hashlib.sha256(audio).hexdigest())
        self.assertEqual(identity.data_size, len(audio))
        self.assertEqual(identity.channels, 2)
        self.assertEqual(identity.bits_per_sample, 16)
        self.assertEqual(chunks, [("fmt ", 12, 16), ("data", 36, 4)])

    def test_tolerates_missing_padding_before_valid_chunk(self) -> None:
        audio = b"\x01\x02\x03"
        identity, chunks = self.parse_temp(
            wav_bytes(
                [
                    chunk(b"fmt ", fmt_payload(bits_per_sample=24)),
                    chunk(b"data", audio, pad=False),
                    chunk(b"ID3 ", b"metadata"),
                ]
            )
        )

        self.assertEqual(identity.data_sha256, hashlib.sha256(audio).hexdigest())
        self.assertEqual(chunks[-1][0], "ID3 ")

    def test_tolerates_final_padding_byte_outside_declared_riff_end(self) -> None:
        audio = b"\x01\x02\x03\x04"
        body_chunks = [
            chunk(b"fmt ", fmt_payload()),
            chunk(b"data", audio),
            chunk(b"ID3 ", b"abc", pad=True),
        ]
        data = wav_bytes(body_chunks, riff_size_delta=-1)

        identity, chunks = self.parse_temp(data)

        self.assertEqual(identity.data_sha256, hashlib.sha256(audio).hexdigest())
        self.assertEqual(chunks[-1], ("ID3 ", 48, 3))

    def test_tolerates_data_chunk_beyond_underdeclared_riff_end(self) -> None:
        audio = b"\x01\x02\x03\x04\x05\x06"
        data = wav_bytes(
            [
                chunk(b"fmt ", fmt_payload()),
                chunk(b"smpl", b"\x00" * 60),
                chunk(b"data", audio),
            ],
            riff_size_delta=-4,
        )

        identity, chunks = self.parse_temp(data)

        self.assertEqual(identity.data_sha256, hashlib.sha256(audio).hexdigest())
        self.assertEqual(chunks[-1][0], "data")


if __name__ == "__main__":
    unittest.main()
