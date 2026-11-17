"""Turn build_schematic arguments into the bridge's pipe-record spec.

Pure formatting: no Altium, no file I/O. main.py writes the returned lines to
circuit_spec.txt and BuildCircuitFromSpec (AltiumScript/schematic_utils.pas)
executes them. Kept apart from main.py so the record format can be exercised
without starting the MCP server.

Record kinds added for drafting on a company frame (2026-11-17):
  TEMPLATEFROM|<sheet path>   copy sheet size, border and the template object
                              (frame + title block) from an existing sheet
  DOCPARAM|<name>|<value>     set a document parameter (title-block fields)
  TEXTFRAME|x1|y1|x2|y2|font|size|bold|align|border|fill|text
  SAVEAS|<path>|<format>      save the new sheet there (never overwrites)
  PROJECT|<path>              add the saved sheet to that open project
"""

import os

FIELD_SEP = "|"
# IServerDocument save format, one of the schematic server's SaveFilters
# (System\Advsch.ins). 'SCH' renamed the document but wrote no file on
# AD26.11.1 (2026-11-17); this name is the one Altium's IServerDocument
# reference lists for schematic documents.
SAVE_KIND_DEFAULT = "Advanced Schematic binary"
# Line break inside a text frame. pcb_utils.pas already uses the same token for
# multi-line PCB text; schematic_utils.pas turns it back into CRLF.
NEWLINE_TOKEN = "<NL>"
ALIGN_CODES = {"left": "L", "center": "C", "right": "R"}


class SpecError(ValueError):
    """Input the record format cannot carry faithfully."""


def _field(value, what):
    text = str(value)
    if FIELD_SEP in text or "\n" in text or "\r" in text:
        raise SpecError(f"{what} must not contain '|' or a line break: {text!r}")
    return text


def _frame_text(value, what):
    text = str(value).replace("\r\n", "\n")
    if FIELD_SEP in text or "\r" in text or NEWLINE_TOKEN in text:
        raise SpecError(f"{what} must not contain '|', a bare CR or {NEWLINE_TOKEN!r}: {text!r}")
    return text.replace("\n", NEWLINE_TOKEN)


def _int(value, what):
    if isinstance(value, bool):
        raise SpecError(f"{what} must be a number, got {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise SpecError(f"{what} must be a number, got {value!r}") from None


def _color(value, what):
    """None -> -1 (no fill). '#RRGGBB' -> Altium TColor, which is 0x00BBGGRR."""
    if value is None:
        return -1
    if isinstance(value, str) and len(value) == 7 and value[0] == "#":
        try:
            r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            raise SpecError(f"{what} is not a #RRGGBB colour: {value!r}") from None
        return r | (g << 8) | (b << 16)
    raise SpecError(f"{what} must be '#RRGGBB' or null, got {value!r}")


def _existing_file(path, suffix, what):
    path = _field(path, what)
    if not os.path.isabs(path) or not path.lower().endswith(suffix.lower()):
        raise SpecError(f"{what} must be an absolute {suffix} path: {path!r}")
    if not os.path.isfile(path):
        raise SpecError(f"{what} does not exist: {path!r}")
    return path


def build_spec_lines(parts, wires=None, junctions=None, net_labels=None,
                     power_ports=None, notes=None, template_from_sheet=None,
                     sheet_parameters=None, text_frames=None, save_as=None,
                     add_to_project=None, save_kind=SAVE_KIND_DEFAULT):
    """Return the spec records for one sheet; raise SpecError on bad input."""
    lines = []

    if template_from_sheet is not None:
        lines.append("TEMPLATEFROM|" + _existing_file(
            template_from_sheet, ".SchDoc", "template_from_sheet"))
    if save_as is not None:
        target = _field(save_as, "save_as")
        if not os.path.isabs(target) or not target.lower().endswith(".schdoc"):
            raise SpecError(f"save_as must be an absolute .SchDoc path: {target!r}")
        if os.path.exists(target):
            raise SpecError(f"save_as already exists, refusing to overwrite: {target!r}")
        if not os.path.isdir(os.path.dirname(target)):
            raise SpecError(f"save_as folder does not exist: {target!r}")
        kind = _field(save_kind, "save_kind")
        if not kind:
            raise SpecError("save_kind must name a schematic save format")
        lines.append(f"SAVEAS|{target}|{kind}")
    if add_to_project is not None:
        if save_as is None:
            raise SpecError("add_to_project needs save_as: a project holds files, "
                            "not unsaved documents")
        lines.append("PROJECT|" + _existing_file(add_to_project, ".PrjPcb", "add_to_project"))

    for p in parts:
        for key in ("designator", "symbol_library", "symbol", "x", "y"):
            if key not in p:
                raise SpecError(f"part missing required key '{key}': {p}")
        lines.append("PART|{}|{}|{}|{}|{}|{}|{}|{}".format(
            p["designator"], p["symbol_library"], p["symbol"],
            p.get("design_item_id", ""), int(p["x"]), int(p["y"]),
            int(p.get("orientation", 0)), 1 if p.get("mirror") else 0))
        if p.get("comment"):
            lines.append(f"COMMENT|{p['comment']}")
        if p.get("footprint"):
            lines.append(f"FOOTPRINT|{p['footprint']}")
        if p.get("description"):
            lines.append(f"DESCRIPTION|{p['description']}")
        for name, val in (p.get("parameters") or {}).items():
            lines.append(f"PARAM|{name}|{val}")

    for route in (wires or []):
        if len(route) < 4 or len(route) % 2:
            raise SpecError(f"wire needs an even count of >=4 coords: {route}")
        lines.append("WIRE|" + "|".join(str(int(v)) for v in route))
    for j in (junctions or []):
        lines.append(f"JUNCTION|{int(j['x'])}|{int(j['y'])}")
    for n in (net_labels or []):
        lines.append("NETLABEL|{}|{}|{}|{}".format(
            int(n["x"]), int(n["y"]), int(n.get("orientation", 0)), n["text"]))
    for pw in (power_ports or []):
        lines.append("POWER|{}|{}|{}|{}|{}|{}".format(
            int(pw["x"]), int(pw["y"]), int(pw.get("orientation", 3)),
            int(pw.get("style", 5)), pw["text"],
            1 if pw.get("show_net_name") else 0))
    for nt in (notes or []):
        lines.append(f"NOTE|{int(nt['x'])}|{int(nt['y'])}|{nt['text']}")

    for name, value in (sheet_parameters or {}).items():
        if not str(name).strip():
            raise SpecError("sheet_parameters has an empty parameter name")
        lines.append("DOCPARAM|{}|{}".format(
            _field(name, "sheet parameter name"), _field(value, f"sheet parameter {name!r}")))

    for k, f in enumerate(text_frames or []):
        what = f"text_frames[{k}]"
        x1, y1, x2, y2 = (_int(f.get(c), f"{what}.{c}") for c in ("x1", "y1", "x2", "y2"))
        if x1 >= x2 or y1 >= y2:
            raise SpecError(f"{what}: need x1 < x2 and y1 < y2 (bottom-left, top-right)")
        size = _int(f.get("size", 10), f"{what}.size")
        if not 4 <= size <= 72:
            raise SpecError(f"{what}.size must be 4..72, got {size}")
        align = ALIGN_CODES.get(f.get("align", "left"))
        if align is None:
            raise SpecError(f"{what}.align must be one of {sorted(ALIGN_CODES)}")
        if "text" not in f:
            raise SpecError(f"{what} missing required key 'text'")
        lines.append("TEXTFRAME|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}".format(
            x1, y1, x2, y2, _field(f.get("font", "Arial"), f"{what}.font"), size,
            1 if f.get("bold") else 0, align, 1 if f.get("border", True) else 0,
            _color(f.get("fill"), f"{what}.fill"), _frame_text(f["text"], f"{what}.text")))

    return lines
