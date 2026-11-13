import re
import unicodedata
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


class _ReportTextParser(HTMLParser):
    _BLOCK_TAGS = {"div", "h1", "h2", "h3", "h4", "p", "li", "tr"}
    _HEADING_TAGS = {"h1", "h2", "h3", "h4"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self._text = []
        self._tag = "p"
        self._ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag in self._BLOCK_TAGS:
            self._flush()
            self._tag = tag if tag in self._HEADING_TAGS else "p"
        elif tag == "br":
            self._flush()
        elif tag in {"td", "th"} and self._text:
            self._text.append(" | ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag in {"td", "th"}:
            self._text.append(" | ")
        elif tag in self._BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if not self._ignored_depth:
            self._text.append(data)

    def close(self):
        super().close()
        self._flush()

    def _flush(self):
        text = " ".join("".join(self._text).split())
        text = "".join(
            character
            for character in text
            if unicodedata.category(character) != "Cc"
        )
        if text:
            self.blocks.append((self._tag, text))
        self._text = []
        self._tag = "p"


def render_html_pdf(html_content):
    parser = _ReportTextParser()
    parser.feed(html_content)
    parser.close()
    if not parser.blocks:
        raise ValueError("The report contains no printable text.")

    font_dir = Path(reportlab.__file__).parent / "fonts"
    if "ExportVera" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("ExportVera", str(font_dir / "Vera.ttf")))

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ExportTitle",
            parent=styles["Title"],
            fontName="ExportVera",
            fontSize=16,
            leading=20,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#1e3a5f"),
            spaceAfter=12,
        )
    )
    for level, size in (("h2", 13), ("h3", 11), ("h4", 10)):
        styles.add(
            ParagraphStyle(
                name=f"Export{level}",
                parent=styles["Heading2"],
                fontName="ExportVera",
                fontSize=size,
                leading=size + 3,
                textColor=colors.HexColor("#1e3a5f"),
                spaceBefore=8,
                spaceAfter=5,
            )
        )
    styles.add(
        ParagraphStyle(
            name="ExportBody",
            parent=styles["BodyText"],
            fontName="ExportVera",
            fontSize=9,
            leading=12,
            spaceAfter=5,
        )
    )

    story = []
    for index, (tag, text) in enumerate(parser.blocks):
        style = styles["ExportTitle"] if index == 0 or tag == "h1" else styles.get(
            f"Export{tag}", styles["ExportBody"]
        )
        story.append(Paragraph(escape(text), style))
        if tag in {"h1", "h2"}:
            story.append(Spacer(1, 3))

    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=42,
        leftMargin=42,
        topMargin=42,
        bottomMargin=42,
    )
    document.build(story)
    return output.getvalue()
