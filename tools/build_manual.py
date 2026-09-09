# -*- coding: utf-8 -*-
"""
أداة توليد كتيب الاستخدام الشامل (PDF) بالعربية — T4crte
التشغيل:  python tools/build_manual.py
التعتمد على: fpdf2 + arabic_reshaper + python-bidi + خط Amiri (docs/fonts)
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import fpdf
import arabic_reshaper
from bidi.algorithm import get_display

from manual_part1 import PART as P1
from manual_part2 import PART as P2
from manual_part3 import PART as P3
from manual_part4 import PART as P4
from manual_part5 import PART as P5

PARTS = [P1, P2, P3, P4, P5]

ARABIC_RE = re.compile(r"[\u0600-\u06FF]")

FONT_DIR = os.path.join(ROOT, "docs", "fonts")
OUT_PDF = os.path.join(ROOT, "docs", "user_manual.pdf")

BODY_SIZE = 11.0
LH_FACTOR = 0.66  # line height factor for Amiri


def rtl(text: str) -> str:
    """تشكيل وترتيب نص عربي مع الحفاظ على النص اللاتيني كما هو"""
    if not ARABIC_RE.search(text or ""):
        return text
    return get_display(arabic_reshaper.reshape(text))


class ManualPdf(fpdf.FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(True, margin=18)
        self.set_margins(16, 18, 16)
        self.add_font("Amiri", "", os.path.join(FONT_DIR, "Amiri-Regular.ttf"))
        self.add_font("Amiri", "B", os.path.join(FONT_DIR, "Amiri-Bold.ttf"))
        self.add_font("Mono", "", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
        self.alias_nb_pages()
        self.section_pages = {}

    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-13)
        self.set_font("Amiri", "", 9)
        self.set_text_color(120, 120, 130)
        txt = rtl(f"الصفحة {self.page_no()} من {self.alias_nb_pages()}  —  Kتيب استخدام T4crte")
        self.cell(0, 6, txt, align="C")


def fit_width(pdf, text, font_size, max_w):
    """قص نص طويل عند حدود السطر (قبل التشكيل) ليعرض على سطر واحد"""
    pdf.set_font("Amiri", "", font_size)
    if pdf.get_string_width(rtl(text)) <= max_w:
        return text
    words = text.split()
    out = []
    for i in range(len(words), 0, -1):
        cand = " ".join(words[:i])
        if pdf.get_string_width(rtl(cand + "…")) <= max_w:
            return cand + "…"
    return words[0] + "…"


class Renderer:
    def __init__(self, pdf: ManualPdf, toc_pages: dict):
        self.pdf = pdf
        self.toc_pages = toc_pages

    # ---------- blocks ----------
    def cover(self):
        p = self.pdf
        p.add_page()
        p.ln(40)
        p.set_font("Amiri", "B", 30)
        p.set_text_color(20, 40, 80)
        p.cell(0, 16, rtl("كتيب الاستخدام الشامل"), align="C", new_x="LMARGIN", new_y="NEXT")
        p.ln(4)
        p.set_font("Amiri", "B", 22)
        p.set_text_color(60, 80, 120)
        p.cell(0, 12, rtl("بوت التداول الفوري الذكي — T4crte Spot Trading Bot"), align="C", new_x="LMARGIN", new_y="NEXT")
        p.ln(10)
        p.set_draw_color(100, 140, 200)
        p.set_line_width(0.6)
        x0, x1 = p.l_margin + 40, p.w - p.r_margin - 40
        p.line(x0, p.get_y(), x1, p.get_y())
        p.ln(10)
        p.set_font("Amiri", "", 13)
        p.set_text_color(70, 70, 80)
        for line in [
            "إصدار 1.1 — سبتمبر 2026",
            "يغطي: التركيب، الاستراتيجية، إدارة المخاطر، كل تبويبات الواجهة،",
            "ربط Bybit و Binance و Telegram و أي ذكاء اصطناعي،",
            "والتشغيل الدائم 24/7 على خوادم مجانية",
        ]:
            p.cell(0, 9, rtl(line), align="C", new_x="LMARGIN", new_y="NEXT")
        p.ln(22)
        # warning box
        y0 = p.get_y()
        p.set_fill_color(253, 243, 235)
        p.set_draw_color(220, 120, 80)
        w = p.w - p.l_margin - p.r_margin - 10
        box_text = rtl(
            "تنبيه هام: هذا الكتيب أداة تعليمية وتشغيلية. البوت لا يضمن أي ربح — الأسواق تحمل مخاطر خسارة حقيقية. "
            "ابدأ دائماً بالمحاكاة الورقية، ثم بيئة التجربة (Testnet)، ثم مبلغاً صغيراً جداً لا تتأثر بخسارته."
        )
        p.set_font("Amiri", "", 11)
        lines = p.multi_cell(w, 8, box_text, align="R", dry_run=True, output="LINES")
        h = len(lines) * 8 + 12
        p.rect(5, y0, w, h, style="FD")
        p.set_xy(p.l_margin + 5, y0 + 6)
        p.multi_cell(w, 8, box_text, align="R")

    def toc(self):
        p = self.pdf
        p.add_page()
        p.set_font("Amiri", "B", 17)
        p.set_text_color(20, 40, 80)
        p.cell(0, 12, rtl("فهرس المحتويات"), align="R", new_x="LMARGIN", new_y="NEXT")
        p.ln(6)
        p.set_draw_color(100, 140, 200)
        p.set_line_width(0.5)
        p.line(p.l_margin, p.get_y(), p.w - p.r_margin, p.get_y())
        p.ln(8)
        p.set_font("Amiri", "", 12)
        for key, title in self.toc_entries():
            num = str(self.toc_pages.get(key, "…"))
            p.set_text_color(40, 40, 50)
            max_w = p.w - p.l_margin - p.r_margin
            title_fit = fit_width(p, title, 12, max_w - 40)
            t_disp = rtl(title_fit)
            n_dots = max(2, int((max_w - p.get_string_width(t_disp) - p.get_string_width(num) - 12) / p.get_string_width(".")))
            line = t_disp + "  " + "." * n_dots + "  " + num
            p.set_font("Amiri", "", 12)
            p.cell(0, 10.5, line, align="R", new_x="LMARGIN", new_y="NEXT")
        p.ln(4)
        p.set_font("Amiri", "", 10)
        p.set_text_color(110, 110, 120)
        p.cell(0, 8, rtl("ملاحظة: الأرقام تعني صفحة البداية لكل فصل — انتقل إليها مباشرة من شريط التنقل في قارئ الـ PDF."), align="R")

    def h1(self, key, title):
        p = self.pdf
        p.add_page()
        p.section_pages[key] = p.page
        p.set_font("Amiri", "B", 17)
        p.set_text_color(20, 40, 80)
        p.multi_cell(0, 11, rtl(title), align="R")
        p.ln(1)
        p.set_draw_color(100, 140, 200)
        p.set_line_width(0.7)
        p.line(p.l_margin, p.get_y(), p.w - p.r_margin, p.get_y())
        p.ln(5)

    def h2(self, title):
        p = self.pdf
        p.ln(3)
        self._ensure_space(14)
        p.set_font("Amiri", "B", 14)
        p.set_text_color(40, 70, 130)
        p.multi_cell(0, 9.5, rtl(title), align="R")
        p.ln(1.5)

    def h3(self, title):
        p = self.pdf
        p.ln(1.5)
        self._ensure_space(12)
        p.set_font("Amiri", "B", 12)
        p.set_text_color(70, 55, 20)
        p.multi_cell(0, 8.5, rtl(title), align="R")
        p.ln(1)

    def _ensure_space(self, h):
        p = self.pdf
        if p.get_y() + h > p.h - 18:
            p.add_page()

    def para(self, text):
        p = self.pdf
        p.set_font("Amiri", "", BODY_SIZE)
        p.set_text_color(35, 35, 45)
        p.multi_cell(0, BODY_SIZE * LH_FACTOR, rtl(text), align="R")
        p.ln(2)

    def bullet(self, text):
        p = self.pdf
        p.set_font("Amiri", "", BODY_SIZE)
        p.set_text_color(35, 35, 45)
        p.set_x(p.l_margin + 8)
        p.multi_cell(p.w - p.l_margin - p.r_margin - 8, BODY_SIZE * LH_FACTOR, "•  " + rtl(text), align="R")
        p.ln(1.2)

    def code(self, text):
        p = self.pdf
        p.set_font("Mono", "", 8.5)
        w = p.w - p.l_margin - p.r_margin - 8
        lines = p.multi_cell(w - 8, 4.6, text, align="L", dry_run=True, output="LINES")
        h = len(lines) * 4.6 + 8
        self._ensure_space(h + 4)
        y0 = p.get_y()
        p.set_fill_color(244, 246, 250)
        p.set_draw_color(200, 205, 215)
        p.rect(p.l_margin + 4, y0, w, h, style="FD")
        p.set_xy(p.l_margin + 8, y0 + 4)
        p.set_font("Mono", "", 8.5)
        p.set_text_color(30, 30, 40)
        p.multi_cell(w - 8, 4.6, text, align="L")
        p.ln(3)

    def callout(self, text, kind):
        p = self.pdf
        self._ensure_space(20)
        if kind == "warn":
            fill = (253, 243, 235)
            edge = (214, 110, 70)
            head = "تنبيه هام"
            head_color = (170, 60, 20)
        else:
            fill = (238, 248, 240)
            edge = (80, 160, 110)
            head = "نصيحة عملية"
            head_color = (30, 110, 60)
        p.set_font("Amiri", "", BODY_SIZE)
        w = p.w - p.l_margin - p.r_margin - 10
        lines = p.multi_cell(w - 10, BODY_SIZE * LH_FACTOR, rtl(text), align="R", dry_run=True, output="LINES")
        h = len(lines) * BODY_SIZE * LH_FACTOR + 14
        y0 = p.get_y()
        p.set_fill_color(*fill)
        p.set_draw_color(*edge)
        p.rect(p.l_margin + 5, y0, w, h, style="FD")
        p.set_xy(p.l_margin + 10, y0 + 4)
        p.set_font("Amiri", "B", 11)
        p.set_text_color(*head_color)
        p.cell(0, 7, rtl(head), align="R", new_x="LMARGIN", new_y="NEXT")
        p.set_x(p.l_margin + 10)
        p.set_font("Amiri", "", BODY_SIZE)
        p.set_text_color(40, 40, 50)
        p.multi_cell(w - 10, BODY_SIZE * LH_FACTOR, rtl(text), align="R")
        p.ln(3)

    def table(self, rows):
        p = self.pdf
        n_cols = len(rows[0])
        if n_cols == 2:
            widths = [0.38, 0.62]
        elif n_cols == 3:
            widths = [0.24, 0.26, 0.50]
        else:
            widths = [1.0 / n_cols] * n_cols
        total_w = p.w - p.l_margin - p.r_margin - 6
        col_w = [total_w * w for w in widths]
        p.set_font("Amiri", "", 9.5)
        for ri, row in enumerate(rows):
            # lines per cell
            cell_lines = []
            for ci, cell in enumerate(row):
                p.set_font("Amiri", "B" if ri == 0 else "", 9.5)
                t = rtl(cell) if ARABIC_RE.search(cell) else cell
                ls = p.multi_cell(col_w[ci] - 4, 5.6, t, align="R" if ARABIC_RE.search(cell) else "L", dry_run=True, output="LINES")
                cell_lines.append(ls if ls else [""])
            row_h = max(len(ls) for ls in cell_lines) * 5.6 + 4
            if p.get_y() + row_h > p.h - 18:
                p.add_page()
            y0 = p.get_y()
            for ci, cell in enumerate(row):
                p.set_font("Amiri", "B" if ri == 0 else "", 9.5)
                is_ar = bool(ARABIC_RE.search(cell))
                t = rtl(cell) if is_ar else cell
                if ri == 0:
                    p.set_fill_color(226, 234, 248)
                    p.set_draw_color(170, 185, 215)
                    p.set_text_color(30, 50, 100)
                else:
                    p.set_fill_color(250, 251, 253)
                    p.set_draw_color(205, 210, 222)
                    p.set_text_color(40, 40, 50)
                x = p.l_margin + 3 + sum(col_w[:ci])
                p.rect(x, y0, col_w[ci], row_h, style="FD")
                p.set_xy(x + 2, y0 + 2)
                p.multi_cell(col_w[ci] - 4, 5.6, t, align="R" if is_ar else "L")
            p.set_y(y0 + row_h)
        p.ln(4)

    # ---------- main ----------
    def toc_entries(self):
        out = []
        n = 0
        for part in PARTS:
            for block in part:
                if block[0] == "h1":
                    n += 1
                    out.append((f"c{n}", block[1]))
        return out

    def render(self):
        p = self.pdf
        self.cover()
        # assign chapter keys in order
        keys = [k for k, _ in self.toc_entries()]
        p.section_pages = {}
        self.toc()
        ci = 0
        for part in PARTS:
            for block in part:
                kind = block[0]
                if kind == "h1":
                    self.h1(keys[ci], block[1])
                    ci += 1
                elif kind == "h2":
                    self.h2(block[1])
                elif kind == "h3":
                    self.h3(block[1])
                elif kind == "p":
                    self.para(block[1])
                elif kind == "li":
                    self.bullet(block[1])
                elif kind == "code":
                    self.code(block[1])
                elif kind == "warn":
                    self.callout(block[1], "warn")
                elif kind == "tip":
                    self.callout(block[1], "tip")
                elif kind == "table":
                    self.table(block[1])
        p.output(OUT_PDF)
        return p.section_pages


def main():
    import time
    t0 = time.time()
    # Pass 1: record chapter pages
    r1 = Renderer(ManualPdf(), toc_pages={})
    pages = r1.render()
    print(f"pass 1: {len(pages)} chapters, pages={pages}")
    # Pass 2: render TOC with real page numbers
    r2 = Renderer(ManualPdf(), toc_pages=pages)
    r2.render()
    size_kb = os.path.getsize(OUT_PDF) / 1024
    print(f"pass 2: wrote {OUT_PDF} ({size_kb:.0f} KB) in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
