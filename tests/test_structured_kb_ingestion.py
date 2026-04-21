from __future__ import annotations

import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nemorax.backend.ingest_nemsu_kb import _extract_contacts_from_directory, _extract_program_rows


class StructuredKbParserTests(unittest.TestCase):
    def test_extract_program_rows_reads_program_table(self) -> None:
        soup = BeautifulSoup(
            """
            <table>
              <tr><th>College of Information Technology Education</th></tr>
              <tr><th>Academic Program</th><th>Level of Accreditation</th></tr>
              <tr><td>Bachelor of Science in Computer Science</td><td>Level II</td></tr>
              <tr><td>Bachelor of Science in Information Technology</td><td>Level III</td></tr>
            </table>
            """,
            "lxml",
        )

        rows = _extract_program_rows(soup, "https://www.nemsu.edu.ph/academics/programs")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["college"], "College of Information Technology Education")
        self.assertEqual(rows[0]["degree_level"], "bachelor")
        self.assertEqual(rows[0]["accreditation"], "Level II")

    def test_extract_contacts_from_directory_reads_table(self) -> None:
        soup = BeautifulSoup(
            """
            <table>
              <tr><th>Name</th><th>Designation</th><th>Contact No.</th><th>Email Address</th></tr>
              <tr><td>Nemesio G. Loayon, Ph.D.</td><td>University President</td><td>(086) 214-4221</td><td>op@nemsu.edu.ph</td></tr>
              <tr><td>Ms. Lynnet A. Sarvida</td><td>AO V / Registrar III</td><td>(086) 214-5069</td><td>registrarmain@nemsu.edu.ph</td></tr>
            </table>
            """,
            "lxml",
        )

        contacts, offices = _extract_contacts_from_directory(soup, "https://www.nemsu.edu.ph/directory")

        self.assertEqual(len(contacts), 2)
        self.assertEqual(contacts[1]["office"], "Registrar")
        self.assertEqual(contacts[1]["email"], "registrarmain@nemsu.edu.ph")
        self.assertEqual(len(offices), 1)
        self.assertEqual(offices[0]["office_name"], "Registrar")


if __name__ == "__main__":
    unittest.main()
