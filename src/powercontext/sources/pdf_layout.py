"""Geometry-aware PDF text extraction, including text inside Form XObjects."""

from __future__ import annotations

from copy import copy
from math import isfinite

from pypdf import PageObject, PdfReader
from pypdf._text_extraction import _layout_mode
from pypdf.generic import ArrayObject, ContentStream, DictionaryObject, FloatObject, NameObject, NullObject


def _text_operations(operands, operator):
    """Make every glyph advance explicit for pypdf's layout state machine.

    Its Tj path records glyphs without advancing the current text matrix. Its TJ
    path advances at the following numeric displacement. An explicit zero after
    each string therefore preserves PDF semantics while avoiding stale positions
    when a producer splits one word over consecutive text-show operations.
    """
    prefix = []
    if operator in (b"'", b'"'):
        if operator == b'"':
            prefix.extend((([operands[0]], b"Tw"), ([operands[1]], b"Tc")))
        prefix.append(([], b"T*"))
        operands, operator = [operands[-1]], b"Tj"
    if operator == b"Tj":
        return [*prefix, ([ArrayObject([operands[0], FloatObject(0)])], b"TJ")]
    if operator != b"TJ":
        return [(operands, operator)]
    values = []
    for value in operands[0]:
        if isinstance(value, (bytes, str)):
            if values and isinstance(values[-1], (bytes, str)):
                values.append(FloatObject(0))
            values.append(value)
        elif values and not isinstance(values[-1], (bytes, str)):
            values[-1] = FloatObject(float(values[-1]) + float(value))
        else:
            values.append(value)
    if values and isinstance(values[-1], (bytes, str)):
        values.append(FloatObject(0))
    return [([ArrayObject(values)], b"TJ")]


def _expanded_page(page: PageObject, reader: PdfReader) -> PageObject:  # noqa: C901
    """Expose each form invocation to the layout extractor in its own resource scope.

    pypdf's layout engine handles text geometry but does not visit ``Do``. Inline
    the referenced content with its matrix and isolated font names. The original
    page, streams and resource dictionaries remain untouched.
    """
    fonts = DictionaryObject()
    font_names: dict[int, NameObject] = {}

    def register_font(font) -> NameObject:
        font = font.get_object()
        identity = id(font)
        if identity not in font_names:
            name = NameObject(f"/PCFont{len(font_names)}")
            font_names[identity] = name
            fonts[name] = font
        return font_names[identity]

    def restore(state):
        return [([FloatObject(value)], operator) for operator, value in state.items()]

    def expand(content, resources, active: frozenset[int], initial):  # noqa: C901
        operations = []
        state = dict(initial)
        saved = []
        if isinstance(content.get_object(), NullObject):
            return operations
        for operands, operator in ContentStream(content, reader, "bytes").operations:
            if operator == b"q":
                saved.append(dict(state))
            elif operator == b"Q" and saved:
                state = saved.pop()
                operations.append(([], b"Q"))
                operations.extend(restore(state))
                continue
            elif operator in state:
                state[operator] = float(operands[0])
            elif operator == b"TD":
                state[b"TL"] = -float(operands[1])
            elif operator == b'"':
                state[b"Tw"], state[b"Tc"] = map(float, operands[:2])
            if operator == b"Tf":
                operands = [register_font(resources["/Font"][operands[0]]), operands[1]]
            elif operator == b"gs":
                extended_state = resources["/ExtGState"][operands[0]]
                if "/Font" in extended_state:
                    font, size = extended_state["/Font"]
                    operations.append(([register_font(font), size], b"Tf"))
                # Other extended graphics state entries do not change text content.
                continue
            elif operator == b"Do":
                form = resources["/XObject"][operands[0]]
                if form.get("/Subtype") != "/Form":
                    continue  # Raster images have no extractable text.
                identity = id(form)
                if identity in active:
                    raise ValueError("Cyclic PDF form invocation")  # noqa: TRY003
                operations.append(([], b"q"))
                if "/Matrix" in form:
                    operations.append((list(form["/Matrix"]), b"cm"))
                operations.extend(
                    expand(form, form.get("/Resources", resources).get_object(), active | {identity}, state)
                )
                operations.append(([], b"Q"))
                operations.extend(restore(state))
                continue
            operations.extend(_text_operations(operands, operator))
        return operations

    contents = ContentStream(None, reader)
    # The layout engine processes cm only inside its q/BT recursion. An outer
    # graphics scope also makes top-level page transforms visible to it.
    contents.operations = [
        ([], b"q"),
        *expand(
            page["/Contents"],
            page.get_inherited("/Resources", DictionaryObject()),
            frozenset(),
            {b"Tc": 0, b"Tw": 0, b"Tz": 100, b"TL": 0, b"Ts": 0},
        ),
        ([], b"Q"),
    ]
    result = copy(page)
    result[NameObject("/Contents")] = contents
    result[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): fonts})
    # Resources have been resolved per invocation; inherited names must not shadow them.
    result.pop("/Parent", None)
    return result


def extract_page_text(page: PageObject, reader: PdfReader) -> str:
    """Extract complete text using glyph geometry, retaining rotated chart labels."""
    if "/Contents" not in page:
        return ""
    expanded = _expanded_page(page, reader)
    # Some Type3 fonts cannot be interpreted by the layout engine. Plain mode
    # still exposes their available Unicode text; never silently discard it.
    fonts = expanded._layout_mode_fonts()
    if any(not font.interpretable for font in fonts.values()):
        return expanded.extract_text() or ""
    groups = _layout_mode.text_show_operations(
        iter(ContentStream(expanded["/Contents"], reader, "bytes").operations), fonts, strip_rotated=False
    )
    if not groups:
        return expanded.extract_text() or ""
    lines = _layout_mode.y_coordinate_groups(groups)
    width = _layout_mode.fixed_char_width(groups)
    if not isfinite(width) or width <= 0:
        return expanded.extract_text() or ""
    for line in lines.values():
        previous = None
        for group in line:
            # Separate independently painted, overlapping runs. Without this,
            # repeated form invocations concatenate the last and first words.
            if previous is not None and group["tx"] <= previous["tx"] and previous["text"].strip():
                group["text"] = " " + group["text"]
            previous = group
    text = _layout_mode.fixed_width_page(lines, width, space_vertically=False, font_height_weight=1)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()
