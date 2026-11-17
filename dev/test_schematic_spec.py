"""Unit tests for server/schematic_spec.py (pure record formatting, no Altium).

Run: python -I dev/test_schematic_spec.py
"""
import os
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
import schematic_spec as ss  # noqa: E402

PART = {"designator": "J1", "symbol_library": r"C:\lib\a.SchLib", "symbol": "A",
        "x": 1000, "y": 2000}


class SpecTests(unittest.TestCase):
    def test_existing_records_unchanged(self):
        lines = ss.build_spec_lines([dict(PART, comment="c")], wires=[[0, 0, 100, 0]],
                                    notes=[{"x": 1, "y": 2, "text": "hi"}])
        self.assertEqual(lines, [r"PART|J1|C:\lib\a.SchLib|A||1000|2000|0|0", "COMMENT|c",
                                 "WIRE|0|0|100|0", "NOTE|1|2|hi"])

    def test_missing_part_key(self):
        with self.assertRaises(ss.SpecError):
            ss.build_spec_lines([{"designator": "J1"}])

    def test_text_frame_record(self):
        lines = ss.build_spec_lines([], text_frames=[{
            "x1": 100, "y1": 200, "x2": 900, "y2": 400, "text": "a\nb", "bold": True,
            "align": "center", "fill": "#E6E6E6"}])
        self.assertEqual(lines, ["TEXTFRAME|100|200|900|400|Arial|10|1|C|1|15132390|a<NL>b"])

    def test_text_frame_rejects_pipe_and_bad_box(self):
        with self.assertRaises(ss.SpecError):
            ss.build_spec_lines([], text_frames=[{"x1": 0, "y1": 0, "x2": 9, "y2": 9, "text": "a|b"}])
        with self.assertRaises(ss.SpecError):
            ss.build_spec_lines([], text_frames=[{"x1": 9, "y1": 0, "x2": 0, "y2": 9, "text": ""}])
        with self.assertRaises(ss.SpecError):
            ss.build_spec_lines([], text_frames=[{"x1": 0, "y1": 0, "x2": 9, "y2": 9, "text": "",
                                                  "fill": "grey"}])

    def test_no_fill_is_minus_one(self):
        lines = ss.build_spec_lines([], text_frames=[{"x1": 0, "y1": 0, "x2": 9, "y2": 9,
                                                      "text": "", "border": False}])
        self.assertEqual(lines, ["TEXTFRAME|0|0|9|9|Arial|10|0|L|0|-1|"])

    def test_doc_params(self):
        lines = ss.build_spec_lines([], sheet_parameters={"Revision": "A", "SheetNumber": 3})
        self.assertEqual(lines, ["DOCPARAM|Revision|A", "DOCPARAM|SheetNumber|3"])
        with self.assertRaises(ss.SpecError):
            ss.build_spec_lines([], sheet_parameters={"Title": "x\ny"})

    def test_save_and_project(self):
        with tempfile.TemporaryDirectory() as d:
            sheet = os.path.join(d, "src.SchDoc")
            prj = os.path.join(d, "p.PrjPcb")
            for p in (sheet, prj):
                open(p, "w").close()
            target = os.path.join(d, "new.SchDoc")
            lines = ss.build_spec_lines([], template_from_sheet=sheet, save_as=target,
                                        add_to_project=prj)
            self.assertEqual(lines, ["TEMPLATEFROM|" + sheet,
                                     "SAVEAS|" + target + "|Advanced Schematic binary",
                                     "PROJECT|" + prj])
            self.assertEqual(ss.build_spec_lines([], save_as=target, save_kind="X Y")[-1],
                             "SAVEAS|" + target + "|X Y")
            with self.assertRaises(ss.SpecError):        # format is required
                ss.build_spec_lines([], save_as=target, save_kind="")
            with self.assertRaises(ss.SpecError):        # never overwrite
                ss.build_spec_lines([], save_as=sheet)
            with self.assertRaises(ss.SpecError):        # project needs a saved file
                ss.build_spec_lines([], add_to_project=prj)
            with self.assertRaises(ss.SpecError):        # template sheet must exist
                ss.build_spec_lines([], template_from_sheet=os.path.join(d, "none.SchDoc"))


if __name__ == "__main__":
    unittest.main()
