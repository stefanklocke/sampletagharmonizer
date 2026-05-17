from __future__ import annotations

import unittest

from sampletagharmonizer.parsers.msgpack_lite import MsgpackDecodeError, decode_prefix


class MsgpackLiteTest(unittest.TestCase):
    def test_rejects_unhashable_map_key_as_decode_error(self) -> None:
        with self.assertRaises(MsgpackDecodeError):
            decode_prefix(b"\x81\x91\x01\x02")


if __name__ == "__main__":
    unittest.main()
