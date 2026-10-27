"""Honor PDF ActualText without changing the original bytes or shared fonts.

The returned page is for text extraction only. Its temporary fonts retain the
painted glyph advances, but map an ActualText span to its replacement once.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from pypdf import PageObject, PdfReader
from pypdf._font import Font
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    ContentStream,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    StreamObject,
    TextStringObject,
    decode_pdfdocencoding,
)

_Operation = tuple[list[Any], bytes]


def _actual_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        if value.startswith((b"\xfe\xff", b"\xff\xfe")):
            return value.decode("utf-16")
        if value.startswith(b"\xef\xbb\xbf"):
            return value.decode("utf-8-sig")
        return decode_pdfdocencoding(value)
    raise ValueError("PDF ActualText must be a text string")  # noqa: TRY003


def _resolved(value):
    return value.get_object() if hasattr(value, "get_object") else value


def _unique_name(resources: DictionaryObject, prefix: str) -> NameObject:
    number = len(resources)
    while NameObject(f"/{prefix}{number}") in resources:
        number += 1
    return NameObject(f"/{prefix}{number}")


@dataclass
class _State:
    font: DictionaryObject | None = None
    size: float = 0
    word_spacing: float = 0
    char_spacing: float = 0
    scale: float = 100
    rise: float = 0
    leading: float = 0
    in_text: bool = False


@dataclass
class _Span:
    text: str | None
    emitted: bool = False


@dataclass
class _ExtractionFont:
    original: Font
    name: NameObject
    resource: DictionaryObject = field(default_factory=DictionaryObject)
    glyphs: list[tuple[str, float]] = field(default_factory=list)
    codes: dict[tuple[str, float], int] = field(default_factory=dict)

    def add(self, text: str, width: float) -> bytes:
        key = (text, width)
        code = self.codes.get(key)
        if code is None:
            code = len(self.glyphs) + 1
            # Keep a dedicated space character for pypdf's spacing heuristics.
            if code >= 32:
                code += 1
            # Identity-H is decoded as UTF-16 by pypdf; surrogate code units
            # must not accidentally combine two independent synthetic glyphs.
            if code >= 0xD800:
                code += 0x800
            self.codes[key] = code
            self.glyphs.append(key)
        return code.to_bytes(2, "big")

    def complete(self) -> None:
        entries = {32: (" ", float(self.original.space_width))}
        entries.update({code: key for key, code in self.codes.items()})
        rows = [f"<{code:04X}> <{text.encode('utf-16-be').hex()}>" for code, (text, _) in entries.items()]
        blocks = []
        for start in range(0, len(rows), 100):
            group = rows[start : start + 100]
            blocks.append(f"{len(group)} beginbfchar\n" + "\n".join(group) + "\nendbfchar")
        cmap = DecodedStreamObject()
        cmap.set_data(
            (
                "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
                "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
                "/CMapName /ActualText-UCS def\n/CMapType 2 def\n"
                "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
                + "\n".join(blocks)
                + "\nendcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
            ).encode("ascii")
        )
        widths = ArrayObject()
        for code, (_, width) in entries.items():
            widths.extend((NumberObject(code), ArrayObject([FloatObject(width)])))
        descriptor = self.original.font_descriptor.as_font_descriptor_resource()
        # These glyphs exist only for extraction; do not attach the original glyph program.
        for key in ("/FontFile", "/FontFile2", "/FontFile3"):
            descriptor.pop(key, None)
        descendant = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/CIDFontType2"),
            NameObject("/BaseFont"): NameObject("/ActualText"),
            NameObject("/CIDSystemInfo"): DictionaryObject({
                NameObject("/Registry"): TextStringObject("Adobe"),
                NameObject("/Ordering"): TextStringObject("Identity"),
                NameObject("/Supplement"): NumberObject(0),
            }),
            NameObject("/FontDescriptor"): descriptor,
            NameObject("/DW"): NumberObject(0),
            NameObject("/W"): widths,
        })
        self.resource.update({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/BaseFont"): NameObject("/ActualText"),
            NameObject("/Encoding"): NameObject("/Identity-H"),
            NameObject("/DescendantFonts"): ArrayObject([descendant]),
            NameObject("/ToUnicode"): cmap,
        })


class _ContentNormalizer:
    def __init__(self, reader: PdfReader) -> None:
        self.reader = reader
        self.fonts: dict[int, Font] = {}

    def prepare(self, page: PageObject) -> PageObject:
        result = PageObject(self.reader)
        result.update(page)
        resources = page.get_inherited("/Resources", DictionaryObject())
        if "/Contents" not in page:
            return result
        operations, resources = self._stream(page["/Contents"], resources, _State(), [], set())
        content = ContentStream(None, self.reader)
        content.operations = operations
        result[NameObject("/Contents")] = content
        result[NameObject("/Resources")] = resources
        return result

    def _font(self, resource: DictionaryObject) -> Font:
        identity = id(resource)
        if identity not in self.fonts:
            self.fonts[identity] = Font.from_font_resource(resource)
        return self.fonts[identity]

    def _stream(self, source, inherited, initial, inherited_spans, active):  # noqa: C901
        resources = DictionaryObject(_resolved(inherited))
        fonts = DictionaryObject(_resolved(resources.get("/Font", DictionaryObject())))
        xobjects = DictionaryObject(_resolved(resources.get("/XObject", DictionaryObject())))
        resources[NameObject("/Font")] = fonts
        resources[NameObject("/XObject")] = xobjects
        state = replace(initial)
        saved = []
        spans = list(inherited_spans)
        depth = len(spans)
        output: list[_Operation] = []
        proxies: dict[int, _ExtractionFont] = {}
        all_proxies = []

        def font_name(font):
            for name, item in fonts.items():
                if _resolved(item) is font:
                    return name
            name = _unique_name(fonts, "ActualTextOriginal")
            fonts[name] = font
            return name

        def proxy_for(font):
            identity = id(font)
            proxy = proxies.get(identity)
            if proxy is None or len(proxy.glyphs) >= 63_485:
                name = _unique_name(fonts, "ActualText")
                proxy = _ExtractionFont(self._font(font), name)
                fonts[name] = proxy.resource
                proxies[identity] = proxy
                all_proxies.append(proxy)
            return proxy

        def show(value, span):
            if state.font is None:
                raise ValueError("PDF ActualText text has no active font")  # noqa: TRY003
            font = self._font(state.font)
            raw = bytes(value) if isinstance(value, bytes) else value.original_bytes
            if isinstance(font.encoding, str):
                decoded = raw.decode(font.encoding, "surrogatepass")
            else:
                decoded = "".join(font.encoding.get(byte, chr(byte)) for byte in raw)
            if not decoded:
                return
            groups = []
            for character in decoded:
                width = font.space_width if character == font.space_char else font.get_text_width(character)
                # A synthetic two-byte code is never a PDF word-spacing character.
                # Retain the old advance in /W while applying Tc to each original glyph.
                if character == font.space_char and state.size:
                    width += state.word_spacing * 1000 / state.size
                text = span.text if not span.emitted else ""
                span.emitted = True
                proxy = proxy_for(state.font)
                code = proxy.add(text, float(width))
                if groups and groups[-1][0] is proxy:
                    groups[-1][1].extend(code)
                else:
                    groups.append((proxy, bytearray(code)))
            output.append(([FloatObject(0)], b"Tw"))
            for proxy, data in groups:
                output.extend((
                    ([proxy.name, FloatObject(state.size)], b"Tf"),
                    ([ByteStringObject(bytes(data))], b"Tj"),
                ))
            output.extend((
                ([font_name(state.font), FloatObject(state.size)], b"Tf"),
                ([FloatObject(state.word_spacing)], b"Tw"),
            ))

        def empty_span(span):
            if span.emitted or not span.text:
                return
            original = replace(state)
            if state.font is None:
                state.font = DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                })
                state.size = 12
            if not state.in_text:
                output.append(([], b"BT"))
            proxy = proxy_for(state.font)
            # A graphics-only replacement has no painted text advance to retain.
            # Give its isolated text object a normal width so layout extraction
            # can represent it; an existing text object must not advance.
            width = 0 if state.in_text else self._font(state.font).get_text_width(span.text)
            code = proxy.add(span.text, width)
            output.extend((
                ([proxy.name, FloatObject(state.size)], b"Tf"),
                ([ByteStringObject(code)], b"Tj"),
            ))
            if not state.in_text:
                output.append(([], b"ET"))
            if original.font is not None:
                output.append(([font_name(original.font), FloatObject(original.size)], b"Tf"))
            state.font, state.size = original.font, original.size
            span.emitted = True

        if initial.font is not None:
            # Plain extraction enters Form XObjects with a fresh text extractor.
            # Make inherited text state explicit; layout inlining sees identical state.
            output.extend((
                ([font_name(initial.font), FloatObject(initial.size)], b"Tf"),
                ([FloatObject(initial.word_spacing)], b"Tw"),
                ([FloatObject(initial.char_spacing)], b"Tc"),
                ([FloatObject(initial.scale)], b"Tz"),
                ([FloatObject(initial.rise)], b"Ts"),
                ([FloatObject(initial.leading)], b"TL"),
            ))

        for operands, operator in ContentStream(source, self.reader, "bytes").operations:
            if operator in (b"BDC", b"BMC"):
                properties = operands[1] if operator == b"BDC" else DictionaryObject()
                if isinstance(properties, NameObject):
                    properties = _resolved(resources.get("/Properties", DictionaryObject()))[properties]
                properties = _resolved(properties)
                value = properties.get("/ActualText")
                spans.append(_Span(None if value is None else _actual_text(value)))
                output.append((operands, operator))
            elif operator == b"EMC":
                if len(spans) == depth:
                    raise ValueError("Unmatched PDF marked-content terminator")  # noqa: TRY003
                span = spans.pop()
                if span.text is not None and not any(item.text is not None for item in spans):
                    empty_span(span)
                output.append((operands, operator))
            elif (
                operator == b"Do"
                and isinstance(child := xobjects[operands[0]], StreamObject)
                and child.get("/Subtype") == "/Form"
            ):
                identity = id(child)
                if identity in active:
                    raise ValueError("Cyclic PDF Form XObject")  # noqa: TRY003
                child_resources = child.get("/Resources", resources)
                child_ops, child_resources = self._stream(child, child_resources, state, spans, active | {identity})
                clone = DecodedStreamObject()
                clone.update({key: value for key, value in child.items() if key not in ("/Filter", "/DecodeParms")})
                child_content = ContentStream(None, self.reader)
                child_content.operations = child_ops
                clone.set_data(child_content.get_data())
                clone[NameObject("/Resources")] = child_resources
                name = _unique_name(xobjects, "ActualTextForm")
                xobjects[name] = clone
                output.append(([name], b"Do"))
            else:
                self._update_state(state, saved, resources, operands, operator)
                owner = next((span for span in spans if span.text is not None), None)
                if owner is not None and operator in (b"Tj", b"TJ", b"'", b'"'):
                    if operator in (b"'", b'"'):
                        if operator == b'"':
                            output.extend((([operands[0]], b"Tw"), ([operands[1]], b"Tc")))
                        output.append(([], b"T*"))
                    values = operands[0] if operator == b"TJ" else [operands[-1]]
                    for value in values:
                        if isinstance(value, (str, bytes)):
                            show(value, owner)
                        else:
                            output.append(([ArrayObject([value])], b"TJ"))
                else:
                    output.append((operands, operator))
        if len(spans) != depth:
            raise ValueError("Unclosed PDF marked-content sequence")  # noqa: TRY003
        for proxy in all_proxies:
            proxy.complete()
        return output, resources

    @staticmethod
    def _update_state(state, saved, resources, operands, operator):  # noqa: C901
        if operator == b"q":
            saved.append(replace(state))
        elif operator == b"Q" and saved:
            previous = saved.pop()
            for attribute in vars(previous):
                setattr(state, attribute, getattr(previous, attribute))
        elif operator == b"Tf":
            state.font = _resolved(resources["/Font"][operands[0]])
            state.size = float(operands[1])
        elif operator == b"gs":
            graphics = _resolved(resources.get("/ExtGState", DictionaryObject()))[operands[0]]
            if "/Font" in graphics:
                font, size = graphics["/Font"]
                state.font, state.size = _resolved(font), float(size)
        elif operator in (b"Tw", b"Tc", b"Tz", b"Ts", b"TL"):
            attribute = {b"Tw": "word_spacing", b"Tc": "char_spacing", b"Tz": "scale", b"Ts": "rise", b"TL": "leading"}[
                operator
            ]
            setattr(state, attribute, float(operands[0]))
        elif operator == b'"':
            state.word_spacing, state.char_spacing = float(operands[0]), float(operands[1])
        elif operator == b"TD":
            state.leading = -float(operands[1])
        elif operator in (b"BT", b"ET"):
            state.in_text = operator == b"BT"


def prepare_page_for_extraction(page: PageObject, reader: PdfReader) -> PageObject:
    """Return an extraction-only copy honoring nested PDF ActualText replacements.

    Original streams, resources, font maps and PDF bytes remain unchanged. Form
    XObjects are copied per invocation so shared forms inherit the calling span.
    """

    return _ContentNormalizer(reader).prepare(page)
