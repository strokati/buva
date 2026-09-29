"""PDF report generation for the workspace (fpdf2 + DejaVu for Cyrillic)."""
import json
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

BASE = Path(__file__).resolve().parent
FONTS = BASE / "fonts"
CONTENT = json.loads((BASE / "static" / "content.json").read_text(encoding="utf-8"))

INK = (23, 32, 51)        # #172033
MUTED = (102, 112, 133)   # #667085
ACCENT = (37, 99, 235)    # #2563eb
DARK = (17, 24, 39)       # #111827
LINE = (229, 231, 235)    # #e5e7eb
SOFT = (239, 246, 255)    # #eff6ff


class ReportPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.add_font("dv", "", str(FONTS / "DejaVuSans.ttf"))
        self.add_font("dv", "B", str(FONTS / "DejaVuSans-Bold.ttf"))
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(auto=True, margin=20)

    def footer(self):
        self.set_y(-13)
        self.set_font("dv", "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 6, f"Germany Business Validation Workspace  ·  {self.page_no()}", align="C")


def _status_tag(st: dict) -> str:
    status = {"Open": "Open", "In progress": "Doing", "Done": "Done"}.get(st["status"], st["status"])
    return f"{status}  ·  {st['confidence']}"


def _section_tasks(content_section: dict, custom: list) -> list:
    tasks = [
        {"id": t["id"], "title": t["title"], "instruction": t.get("instruction", "")}
        for t in content_section["tasks"]
    ]
    tasks += [
        {"id": f"CUSTOM-{c['id']}", "title": c["title"], "instruction": c["instruction"]}
        for c in custom
    ]
    return tasks


def build_pdf(state: dict, username: str) -> bytes:
    """Render the filled workspace (state from _state_payload) into a PDF report."""
    sections_state = state["sections"]
    tasks_state = state["tasks"]
    custom_by_section: dict[int, list] = {}
    for c in state["customTasks"]:
        custom_by_section.setdefault(c["section"], []).append(c)

    def st_of(task_id: str) -> dict:
        return tasks_state.get(task_id) or {"answer": "", "source": "", "status": "Open", "confidence": "D", "evidence": []}

    known_ids = [t["id"] for s in CONTENT["sections"] for t in s["tasks"]] + [
        f"CUSTOM-{c['id']}" for c in state["customTasks"]
    ]
    done = sum(1 for i in known_ids if st_of(i)["status"] == "Done")
    evidence_n = sum(
        (1 if st_of(i)["source"].strip() else 0) + sum(1 for e in st_of(i)["evidence"] if e["value"].strip())
        for i in known_ids
    )
    total = len(known_ids)

    pdf = ReportPDF()
    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")

    # --- cover -----------------------------------------------------------------
    pdf.add_page()
    pdf.set_fill_color(*DARK)
    pdf.rect(0, 0, 210, 74, style="F")
    pdf.set_y(20)
    pdf.set_font("dv", "", 8)
    pdf.set_text_color(147, 197, 253)
    pdf.cell(0, 5, "GERMANY-FIRST  ·  EVIDENCE-FIRST  ·  ECONOMICS-FIRST", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_y(28)
    pdf.set_font("dv", "B", 25)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, "Business Validation Workspace", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("dv", "", 9.5)
    pdf.set_text_color(219, 227, 239)
    pdf.cell(0, 6, f"Звіт робочого простору  ·  {today}  ·  користувач: {username}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_y(84)
    pdf.set_font("dv", "B", 10)
    pdf.set_text_color(*INK)
    pdf.cell(0, 6, "Загальний прогрес", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("dv", "", 9.5)
    pct = round(done / total * 100) if total else 0
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, f"{done} з {total} задач виконано ({pct}%)  ·  {evidence_n} джерел/доказів  ·  "
                   f"{len(state['customTasks'])} додаткових задач", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # progress bar
    pdf.set_y(pdf.get_y() + 3)
    pdf.set_fill_color(*LINE)
    pdf.rect(16, pdf.get_y(), 178, 3.2, style="F")
    if pct:
        pdf.set_fill_color(*ACCENT)
        pdf.rect(16, pdf.get_y(), max(178 * pct / 100, 1.5), 3.2, style="F")

    # --- table of contents -------------------------------------------------------
    pdf.set_y(pdf.get_y() + 12)
    pdf.set_font("dv", "B", 12)
    pdf.set_text_color(*INK)
    pdf.cell(0, 7, "Зміст", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("dv", "", 8.5)
    for s in CONTENT["sections"]:
        tasks = _section_tasks(s, custom_by_section.get(s["num"], []))
        d = sum(1 for t in tasks if st_of(t["id"])["status"] == "Done")
        pdf.set_text_color(*ACCENT)
        pdf.cell(10, 5.4, f"{s['num']:02d}")
        pdf.set_text_color(*INK)
        pdf.cell(122, 5.4, s["title"])
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 5.4, f"{d}/{len(tasks)}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # --- sections ------------------------------------------------------------------
    last_phase = None
    for s in CONTENT["sections"]:
        phase = s["phase"][1]
        if phase != last_phase:
            last_phase = phase
            pdf.add_page()
            pdf.set_font("dv", "B", 8)
            pdf.set_text_color(*MUTED)
            pdf.cell(0, 5, f"PHASE {s['phase'][0]}  ·  {phase}  —  {CONTENT['phaseNames'].get(phase, '')}",
                     new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(2)

        pdf.set_font("dv", "B", 14)
        pdf.set_text_color(*INK)
        pdf.multi_cell(0, 7, f"{s['num']:02d}. {s['title']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("dv", "", 8.5)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(0, 4.6, s["objective"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        ss = sections_state.get(str(s["num"])) or {}
        note = (ss.get("note") or "").strip()
        key_number = (ss.get("key_number") or "").strip()
        if note or key_number:
            pdf.ln(1.5)
            pdf.set_font("dv", "B", 7)
            pdf.set_text_color(*ACCENT)
            pdf.cell(0, 4, "ПІДСУМОК РОЗДІЛУ", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            body = []
            if note:
                body.append("Висновок: " + note)
            if key_number:
                body.append("Ключова цифра: " + key_number)
            pdf.set_fill_color(*SOFT)
            pdf.set_font("dv", "", 8.5)
            pdf.set_text_color(*INK)
            pdf.multi_cell(0, 4.4, "\n".join(body), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)

        for t in _section_tasks(s, custom_by_section.get(s["num"], [])):
            st = st_of(t["id"])
            filled = bool(st["answer"].strip() or st["source"].strip() or any(e["value"].strip() for e in st["evidence"]))
            if pdf.get_y() > 250:
                pdf.add_page()
            # task header line
            pdf.set_font("dv", "B", 9)
            pdf.set_text_color(*ACCENT)
            pdf.cell(14, 5.2, t["id"])
            pdf.set_text_color(*INK)
            title_w = 128
            pdf.multi_cell(title_w, 5.2, t["title"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font("dv", "", 7)
            pdf.set_text_color(*MUTED)
            if t["instruction"]:
                pdf.multi_cell(0, 4, t["instruction"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font("dv", "", 7)
            pdf.set_text_color(*MUTED)
            pdf.cell(0, 4, _status_tag(st) + ("" if filled else "  ·  без відповіді"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            if st["answer"].strip():
                pdf.set_font("dv", "", 8.5)
                pdf.set_text_color(*INK)
                pdf.multi_cell(0, 4.4, st["answer"].strip(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            if st["source"].strip():
                pdf.set_font("dv", "", 8)
                pdf.set_text_color(*ACCENT)
                pdf.multi_cell(0, 4.2, "Джерело: " + st["source"].strip(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            for e in st["evidence"]:
                if e["value"].strip():
                    pdf.set_font("dv", "", 8)
                    pdf.set_text_color(*MUTED)
                    pdf.multi_cell(0, 4.2, "· " + e["value"].strip(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_draw_color(*LINE)
            pdf.line(16, pdf.get_y() + 1, 194, pdf.get_y() + 1)
            pdf.ln(3.5)
        pdf.ln(3)

    # --- appendix: definitions & sources ----------------------------------------------
    pdf.add_page()
    pdf.set_font("dv", "B", 13)
    pdf.set_text_color(*INK)
    pdf.cell(0, 7, "Calculation Definitions", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    for name, descr in CONTENT["calcDefs"]:
        pdf.set_font("dv", "B", 8.5)
        pdf.set_text_color(*ACCENT)
        pdf.multi_cell(0, 4.6, name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("dv", "", 8.5)
        pdf.set_text_color(*INK)
        pdf.multi_cell(0, 4.4, descr, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.2)

    pdf.ln(4)
    pdf.set_font("dv", "B", 13)
    pdf.set_text_color(*INK)
    pdf.cell(0, 7, "Початкові офіційні джерела", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    for name, descr, url in CONTENT["starterSources"]:
        pdf.set_font("dv", "B", 8.5)
        pdf.set_text_color(*INK)
        pdf.multi_cell(0, 4.6, name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("dv", "", 8.5)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(0, 4.4, descr, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(*ACCENT)
        pdf.multi_cell(0, 4.4, url, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.2)

    return bytes(pdf.output())
