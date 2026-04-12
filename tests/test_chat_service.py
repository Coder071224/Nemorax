from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.backend.services.chat import clean_nemis_reply


class ChatServiceFormattingTests(unittest.TestCase):
    def test_clean_nemis_reply_removes_asterisks_and_extra_spacing(self) -> None:
        raw = "Here is **important** info.\n\n\nPlease *read* this."
        self.assertEqual(clean_nemis_reply(raw), "Here is important info.\n\nPlease read this.")


if __name__ == "__main__":
    unittest.main()
