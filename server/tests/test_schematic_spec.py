"""Sheet-level build_schematic records (fork addition, no Altium needed).

Run from server/:  python -m unittest tests.test_schematic_spec -v
"""
import os
import tempfile
import unittest

import schematic_spec as ss


class SheetLinesTests(unittest.TestCase):
    def test_nothing_asked_gives_no_records(self):
        self.assertEqual(ss.sheet_lines(), [])

    def test_text_frame_record_uses_altium_units(self):
        lines = ss.sheet_lines(text_frames=[{
            "x1": 100, "y1": 200, "x2": 900.5, "y2": 400, "text": "a\nb", "bold": True,
            "align": "center", "fill": "#E6E6E6"}])
        self.assertEqual(lines, ["TEXTFRAME|1000000|2000000|9005000|4000000|Arial|10|1|C|1|15132390|a<NL>b"])

    def test_text_frame_rejects_pipe_bad_box_bad_fill(self):
        for frame in ({"x1": 0, "y1": 0, "x2": 9, "y2": 9, "text": "a|b"},
                      {"x1": 9, "y1": 0, "x2": 0, "y2": 9, "text": ""},
                      {"x1": 0, "y1": 0, "x2": 9, "y2": 9, "text": "", "fill": "grey"},
                      {"x1": 0, "y1": 0, "x2": 9, "y2": 9, "text": "", "size": 10.5},
                      {"x1": True, "y1": 0, "x2": 9, "y2": 9, "text": ""},
                      {"x1": float("nan"), "y1": 0, "x2": 9, "y2": 9, "text": ""}):
            with self.assertRaises(ss.SpecError, msg=frame):
                ss.sheet_lines(text_frames=[frame])

    def test_no_fill_is_minus_one(self):
        lines = ss.sheet_lines(text_frames=[{"x1": 0, "y1": 0, "x2": 9, "y2": 9,
                                             "text": "", "border": False}])
        self.assertEqual(lines, ["TEXTFRAME|0|0|90000|90000|Arial|10|0|L|0|-1|"])

    def test_doc_params(self):
        lines = ss.sheet_lines(sheet_parameters={"Revision": "A", "SheetNumber": 3})
        self.assertEqual(lines, ["DOCPARAM|Revision|A", "DOCPARAM|SheetNumber|3"])
        with self.assertRaises(ss.SpecError):
            ss.sheet_lines(sheet_parameters={"Title": "x\ny"})
        with self.assertRaises(ss.SpecError):
            ss.sheet_lines(sheet_parameters={" ": "x"})

    def test_save_and_project(self):
        with tempfile.TemporaryDirectory() as d:
            sheet = os.path.join(d, "src.SchDoc")
            prj = os.path.join(d, "p.PrjPcb")
            for p in (sheet, prj):
                open(p, "w").close()
            target = os.path.join(d, "new.SchDoc")
            lines = ss.sheet_lines(template_from_sheet=sheet, save_as=target, add_to_project=prj)
            self.assertEqual(lines, ["TEMPLATEFROM|" + sheet,
                                     "SAVEAS|" + target + "|Advanced Schematic binary",
                                     "PROJECT|" + prj])
            self.assertEqual(ss.sheet_lines(save_as=target, save_kind="X Y")[-1],
                             "SAVEAS|" + target + "|X Y")
            with self.assertRaises(ss.SpecError):        # format is required
                ss.sheet_lines(save_as=target, save_kind="")
            with self.assertRaises(ss.SpecError):        # never overwrite
                ss.sheet_lines(save_as=sheet)
            with self.assertRaises(ss.SpecError):        # project needs a saved file
                ss.sheet_lines(add_to_project=prj)
            with self.assertRaises(ss.SpecError):        # template sheet must exist
                ss.sheet_lines(template_from_sheet=os.path.join(d, "none.SchDoc"))


if __name__ == "__main__":
    unittest.main()
