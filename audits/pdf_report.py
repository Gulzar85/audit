"""Generate a professional PDF audit report using reportlab directly.

This replaces the previous HTML -> PDF approach (xhtml2pdf / weasyprint) with
reportlab's platypus so we have full control over layout, typography and page
structure without relying on an HTML renderer.
"""
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable, NextPageTemplate, PageBreak,
)
from reportlab.platypus.flowables import Flowable


PAGE_W, PAGE_H = A4
MARGIN = 40


# ---------------------------------------------------------------------------
# Colour / palette helpers
# ---------------------------------------------------------------------------
def _hex(s):
    """Parse a #RRGGBB string into a reportlab colour. Returns None if bad."""
    if not s:
        return None
    s = str(s).lstrip('#')
    if len(s) != 6:
        return None
    try:
        return colors.Color(
            int(s[0:2], 16) / 255.0,
            int(s[2:4], 16) / 255.0,
            int(s[4:6], 16) / 255.0,
        )
    except ValueError:
        return None


def make_palette(business):
    primary = _hex(getattr(business, 'primary_color', None)) or colors.HexColor('#DA291C')
    secondary = _hex(getattr(business, 'secondary_color', None)) or colors.HexColor('#FFC72C')
    accent = _hex(getattr(business, 'accent_color', None)) or colors.HexColor('#27251F')
    return {
        'primary': primary,
        'secondary': secondary,
        'accent': accent,
        'ink': colors.HexColor('#212529'),
        'muted': colors.HexColor('#6c757d'),
        'faint': colors.HexColor('#adb5bd'),
        'border': colors.HexColor('#e9ecef'),
        'bg': colors.HexColor('#f8f9fa'),
        'good': colors.HexColor('#198754'),
        'warn': colors.HexColor('#B8860B'),
        'bad': colors.HexColor('#C0392B'),
        'white': colors.white,
    }


PASS = 'PASS'
PART = 'PART'
FAIL = 'FAIL'
NA = 'N/A'


def score_status(resp):
    if resp.is_na:
        return NA
    possible = resp.question.possible_points
    if resp.scored_points == possible:
        return PASS
    if resp.scored_points > 0:
        return PART
    return FAIL


# ---------------------------------------------------------------------------
# Custom flowables
# ---------------------------------------------------------------------------
class CoverBlock(Flowable):
    """Branded hero banner used on the cover page."""

    def __init__(self, business, palette, restaurant, audit, width, height=150):
        super().__init__()
        self.business = business
        self.palette = palette
        self.restaurant = restaurant
        self.audit = audit
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        p = self.palette

        # Background fill (rounded primary block)
        c.setFillColor(p['primary'])
        c.roundRect(0, 0, self.width, self.height, 12, stroke=0, fill=1)

        x = 24
        y = self.height - 22

        # Company name
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.85))
        c.setFont('Helvetica-Bold', 9)
        company = getattr(self.business, 'company_name', None) or 'Audit Report'
        c.drawString(x, y + 4, str(company).upper())

        # Status badge (top right)
        badge = 'SUBMITTED' if self.audit.is_submitted else 'DRAFT'
        c.setFont('Helvetica', 8)
        badge_w = c.stringWidth(badge, 'Helvetica', 8)
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.18))
        c.roundRect(self.width - 24 - badge_w - 14, y, badge_w + 14, 14, 7,
                    stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.drawString(self.width - 24 - badge_w - 7, y + 4, badge)

        # Restaurant name
        c.setFillColor(colors.white)
        c.setFont('Helvetica-Bold', 26)
        c.drawString(x, y - 34, self.restaurant.name)
        c.setFont('Helvetica', 11)
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.9))
        sub = '#%s  \u2022  %s (v%s)' % (
            self.restaurant.code, self.audit.template.name, self.audit.template.version)
        c.drawString(x, y - 52, sub)

        # Auditor / date
        c.setFont('Helvetica', 10)
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.85))
        auditor = ((self.audit.auditor.get_full_name() or self.audit.auditor.username)
                   if self.audit.auditor else 'Unassigned')
        c.drawString(x, y - 70, 'Audited by %s on %s' % (
            auditor, self.audit.audit_date.strftime('%d %b %Y')))

        # Grade circle (right side)
        gd = 56
        gx = self.width - 24 - gd
        gy = y - 18  # top-ish of the circle
        cy = gy - gd
        c.setLineWidth(2)
        c.setStrokeColor(colors.Color(1, 1, 1, alpha=0.7))
        c.circle(gx + gd / 2, cy + gd / 2, gd / 2, stroke=1, fill=0)
        c.setFillColor(colors.white)
        c.setFont('Helvetica-Bold', 22)
        c.drawCentredString(gx + gd / 2, cy + gd / 2 + 2,
                            str(self.audit.grade or '\u2014'))
        c.setFont('Helvetica', 6.5)
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.75))
        c.drawCentredString(gx + gd / 2, cy + 4,
                            (self.audit.get_grade_display() or 'Grade').upper())

        # Contact / address bottom row
        c.setFont('Helvetica', 8)
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.6))
        parts = []
        if getattr(self.business, 'address', None):
            parts.append(str(self.business.address))
        if getattr(self.business, 'phone', None):
            parts.append(str(self.business.phone))
        if parts:
            c.drawString(x, 12, '  \u2022  '.join(parts))


class ScoreCardGrid(Flowable):
    """Row of summary score cards."""

    def __init__(self, cards, width, card_height=60):
        super().__init__()
        self.cards = cards  # list of (value, label, sub, color)
        self.width = width
        self.card_height = card_height

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        return (self.width, self.card_height)

    def draw(self):
        c = self.canv
        n = len(self.cards)
        gap = 8
        card_w = (self.width - gap * (n - 1)) / n
        for i, (value, label, sub, color) in enumerate(self.cards):
            x = i * (card_w + gap)
            c.setFillColor(colors.HexColor('#f8f9fa'))
            c.roundRect(x, 0, card_w, self.card_height, 8, stroke=0, fill=1)
            c.setStrokeColor(colors.HexColor('#e9ecef'))
            c.setLineWidth(0.5)
            c.roundRect(x, 0, card_w, self.card_height, 8, stroke=1, fill=0)
            c.setFillColor(color)
            c.setFont('Helvetica-Bold', 16)
            c.drawCentredString(x + card_w / 2, self.card_height - 24, str(value))
            c.setFillColor(colors.HexColor('#6c757d'))
            c.setFont('Helvetica-Bold', 7)
            c.drawCentredString(x + card_w / 2, self.card_height - 39, label.upper())
            c.setFont('Helvetica', 6.5)
            c.setFillColor(colors.HexColor('#adb5bd'))
            c.drawCentredString(x + card_w / 2, 6, str(sub))


# ---------------------------------------------------------------------------
# Page templates (header + footer)
# ---------------------------------------------------------------------------
def _on_page(canv, doc):
    """Draw page header + footer on body pages."""
    p = doc.palette
    canv.saveState()
    canv.setFont('Helvetica-Bold', 8)
    canv.setFillColor(p['muted'])
    company = (doc.business.company_name or 'Audit Report').upper()
    canv.drawString(MARGIN, PAGE_H - 28, company)
    canv.drawRightString(PAGE_W - MARGIN, PAGE_H - 28, 'AUDIT REPORT')
    canv.setStrokeColor(p['border'])
    canv.setLineWidth(0.6)
    canv.line(MARGIN, PAGE_H - 36, PAGE_W - MARGIN, PAGE_H - 36)
    canv.setFont('Helvetica', 8)
    canv.setFillColor(p['faint'])
    canv.drawCentredString(PAGE_W / 2, 18, 'Page %d' % canv.getPageNumber())
    canv.line(MARGIN, 36, PAGE_W - MARGIN, 36)
    canv.restoreState()


def _on_cover(canv, doc):
    """Simple footer for the cover page (no header)."""
    p = doc.palette
    canv.saveState()
    canv.setFont('Helvetica', 8)
    canv.setFillColor(p['faint'])
    canv.drawCentredString(PAGE_W / 2, 18, 'Page %d' % canv.getPageNumber())
    canv.restoreState()


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def _styles(p):
    s = getSampleStyleSheet()
    return {
        'h2': ParagraphStyle('h2', parent=s['Heading2'], fontName='Helvetica-Bold',
                             fontSize=13, leading=16, textColor=p['primary'],
                             spaceBefore=10, spaceAfter=4),
        'body': ParagraphStyle('body', parent=s['Normal'], fontName='Helvetica',
                               fontSize=9, leading=12, textColor=p['ink']),
        'small': ParagraphStyle('small', parent=s['Normal'], fontName='Helvetica',
                                fontSize=8, leading=10, textColor=p['muted']),
        'muted': ParagraphStyle('muted', fontName='Helvetica', fontSize=8.5,
                                leading=11, textColor=p['muted']),
        'muted-bold': ParagraphStyle('muted-bold', fontName='Helvetica-Bold', fontSize=8,
                                     leading=10, textColor=p['muted']),
        'cell': ParagraphStyle('cell', fontName='Helvetica', fontSize=8.5, leading=11,
                               textColor=p['ink']),
        'cell-bold': ParagraphStyle('cell-bold', fontName='Helvetica-Bold', fontSize=8.5,
                                    leading=11, textColor=p['ink']),
        'cell-center': ParagraphStyle('cell-center', fontName='Helvetica', fontSize=8.5,
                                      leading=11, alignment=TA_CENTER, textColor=p['ink']),
        'cell-status': ParagraphStyle('cell-status', fontName='Helvetica-Bold', fontSize=8.5,
                                      leading=11, alignment=TA_CENTER),
        'section-title': ParagraphStyle('section-title', fontName='Helvetica-Bold',
                                        fontSize=11, leading=13, textColor=colors.white),
        'section-score': ParagraphStyle('section-score', fontName='Helvetica-Bold',
                                        fontSize=11, leading=13, textColor=p['secondary'],
                                        alignment=TA_RIGHT),
        'sig-label': ParagraphStyle('sig-label', fontName='Helvetica-Bold', fontSize=8,
                                    leading=10, textColor=p['muted']),
        'sig-name': ParagraphStyle('sig-name', fontName='Helvetica-Bold', fontSize=10,
                                   leading=13, textColor=p['ink'], alignment=TA_CENTER),
        'sig-role': ParagraphStyle('sig-role', fontName='Helvetica', fontSize=8,
                                   leading=10, textColor=p['faint'], alignment=TA_CENTER),
    }


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def _score_cards(audit, summary, palette):
    p = palette
    pct = audit.total_percentage
    if pct is None:
        score_color = p['ink']
        score_txt = 'N/A'
    else:
        score_color = p['good'] if pct >= 90 else (p['warn'] if pct >= 80 else p['bad'])
        score_txt = '%.1f%%' % pct
    return [
        (score_txt, 'Overall Score',
         '%s / %s' % (audit.total_scored, audit.total_possible), score_color),
        (str(summary['critical']), 'Critical',
         'Failures' if audit.has_critical_failure else 'All clear',
         p['bad'] if audit.has_critical_failure else p['good']),
        (str(summary['sections']), 'Sections', 'Evaluated', p['ink']),
        ('%s/%s' % (summary['answered'], summary['total']), 'Breakdown',
         '%sP / %sPrt / %sF / %sN' % (
             summary['passed'], summary['partial'], summary['failed'], summary['na']),
         p['ink']),
    ]


def _two_column(left_flows, right_flows, palette):
    """Lay out two equal-width columns side by side using nested tables."""
    widths = [(PAGE_W - 2 * MARGIN) / 2] * 2
    left = Table([[f] for f in left_flows], colWidths=[widths[0] - 6])
    right = Table([[f] for f in right_flows], colWidths=[widths[1] - 6])
    t = Table([[left, right]], colWidths=widths)
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return t


def _details_table(audit, styles, palette):
    rows = []
    rows.append([Paragraph('Restaurant', styles['muted']),
                 Paragraph('#%s %s' % (audit.restaurant.code, audit.restaurant.name),
                           styles['cell-bold'])])
    rows.append([Paragraph('Manager on Duty', styles['muted']),
                 Paragraph(audit.manager_on_duty or '\u2014', styles['cell'])])
    auditor = ((audit.auditor.get_full_name() or audit.auditor.username)
               if audit.auditor else 'Unassigned')
    rows.append([Paragraph('Auditor', styles['muted']), Paragraph(auditor, styles['cell'])])
    rows.append([Paragraph('Date', styles['muted']),
                 Paragraph(audit.audit_date.strftime('%d %b %Y'), styles['cell'])])
    if audit.submitted_at:
        rows.append([Paragraph('Submitted', styles['muted']),
                     Paragraph(audit.submitted_at.strftime('%d %b %Y'), styles['cell'])])
    t = Table(rows, colWidths=[None])
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -2), 0.4, palette['border']),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    return t


def _trend_block(audit, styles, palette):
    prev = audit.previous_audit
    if (not prev or prev.total_percentage is None or audit.total_percentage is None):
        return Paragraph('No previous audit data available', styles['muted'])
    diff = audit.total_percentage - prev.total_percentage
    up = diff >= 0
    color = palette['good'] if up else palette['bad']
    diff_style = ParagraphStyle('t', fontName='Helvetica-Bold', fontSize=8.5,
                                leading=11, textColor=color)
    rows = [
        [Paragraph('Previous', styles['muted']),
         Paragraph('%.1f%%' % prev.total_percentage, styles['cell-bold'])],
        [Paragraph('Current', styles['muted']),
         Paragraph('%.1f%%' % audit.total_percentage, styles['cell-bold'])],
        [Paragraph('Change', styles['muted']),
         Paragraph('%+.1f%%' % diff, diff_style)],
    ]
    t = Table(rows, colWidths=[None])
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -2), 0.4, palette['border']),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    return t


def _section_header(section, index, palette):
    title = Paragraph('<b>%d.&nbsp;&nbsp;%s</b>' % (index, section.section.name),
                      palette['_section_title'])
    pct = section.section_percentage
    score = Paragraph('%s%%&nbsp;&nbsp;<font size=7 color="#f5f5f5">%s / %s</font>' % (
        '%.1f' % pct if pct is not None else '0.0',
        section.scored_points, section.possible_points), palette['_section_score'])
    t = Table([[title, score]], colWidths=[None, 130], rowHeights=[24])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), palette['primary']),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return t


def _question_table(audit_section, styles, palette):
    header = [Paragraph('#', styles['cell-bold']), Paragraph('Question', styles['cell-bold']),
              Paragraph('Score', styles['cell-bold']), Paragraph('Status', styles['cell-bold']),
              Paragraph('Critical', styles['cell-bold'])]
    data = [header]
    n = 1
    for resp in audit_section.responses.all():
        if not resp.is_answered:
            continue
        status = score_status(resp)
        if status == PASS:
            sc = palette['good']
        elif status == PART:
            sc = palette['warn']
        elif status == FAIL:
            sc = palette['bad']
        else:
            sc = palette['faint']
        score_txt = ('\u2014' if resp.is_na
                     else '%s / %s' % (resp.scored_points, resp.question.possible_points))
        critical = '\u25CF' if resp.question.is_critical else ''
        q_text = str(resp.question.question_text)
        if resp.comments:
            q_text += ('<br/><font size=7 color="#8a8a8a"><b>Note:</b> %s</font>'
                       % str(resp.comments))
        data.append([
            Paragraph(str(n), styles['cell-center']),
            Paragraph(q_text, styles['cell']),
            Paragraph(score_txt, styles['cell-center']),
            Paragraph('<font color="%s">%s</font>' % (sc, status), styles['cell-status']),
            Paragraph(critical, styles['cell-center']),
        ])
        n += 1
    t = Table(data, colWidths=[22, None, 46, 44, 42], repeatRows=1)
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, 0), 0.8, palette['ink']),
        ('LINEBELOW', (0, 1), (-1, -1), 0.3, palette['border']),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, palette['bg']]),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return t


def _corrective_action_flows(actions, palette, styles):
    out = []
    for ca in actions:
        dot = (palette['good'] if ca.completed else
               palette['bad'] if ca.is_overdue else palette['faint'])
        status_color = (palette['good'] if ca.completed else
                        palette['bad'] if ca.is_overdue else palette['warn'])
        assignee = ca.assigned_to
        assignee_txt = ((assignee.get_full_name() or assignee.username)
                        if assignee else 'Unassigned')
        out.append(Paragraph(
            '<font color="%s">\u25CF</font>&nbsp;&nbsp;<b>%s</b>' % (dot, ca.description),
            styles['cell']))
        out.append(Paragraph(
            '<font size=7.5 color="#6c757d">Risk: <b>%s</b> &nbsp;\u2022&nbsp; Status: '
            '<font color="%s"><b>%s</b></font> &nbsp;\u2022&nbsp; %s &nbsp;\u2022&nbsp; '
            'Due %s</font>' % (
                ca.get_risk_level_display(), status_color, ca.get_status_display(),
                assignee_txt, ca.deadline.strftime('%d %b %Y')),
            styles['small']))
        if ca.comments:
            out.append(Paragraph('<font size=7.5 color="#adb5bd">%s</font>' % ca.comments,
                                 styles['small']))
        out.append(Spacer(1, 8))
    return out


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------
def build_document(audit, summary, business, critical_fail_count, target):
    """Build the full PDF into target (file path or file-like object)."""
    palette = make_palette(business)
    palette['_section_title'] = ParagraphStyle(
        'st', fontName='Helvetica', fontSize=11, leading=13, textColor=colors.white)
    palette['_section_score'] = ParagraphStyle(
        'ss', fontName='Helvetica-Bold', fontSize=11, leading=13,
        textColor=palette['secondary'], alignment=TA_RIGHT)
    styles = _styles(palette)

    doc = BaseDocTemplate(
        target, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=48, bottomMargin=44,
        title='Audit Report - %s' % audit.restaurant.name,
        author=getattr(business, 'company_name', None) or 'Audit',
        subject=audit.template.name,
    )
    doc.business = business
    doc.palette = palette
    frame_cover = Frame(MARGIN, 44, PAGE_W - 2 * MARGIN, PAGE_H - 44 - 40,
                        id='cover', leftPadding=0, rightPadding=0, topPadding=0,
                        bottomPadding=0)
    frame_body = Frame(MARGIN, 44, PAGE_W - 2 * MARGIN, PAGE_H - 48 - 40, id='body')
    doc.addPageTemplates([
        PageTemplate(id='cover', frames=[frame_cover], onPage=_on_cover),
        PageTemplate(id='body', frames=[frame_body], onPage=_on_page),
    ])

    story = []

    # ---------------- Cover ----------------
    story.append(CoverBlock(business, palette, audit.restaurant, audit,
                            PAGE_W - 2 * MARGIN, height=150))
    story.append(Spacer(1, 14))
    cards = _score_cards(audit, summary, palette)
    story.append(ScoreCardGrid(cards, PAGE_W - 2 * MARGIN))
    story.append(Spacer(1, 14))
    story.append(_two_column(
        [Paragraph('<font color="%s">DETAILS</font>' % palette['primary'], styles['h2']),
         _details_table(audit, styles, palette)],
        [Paragraph('<font color="%s">TREND</font>' % palette['primary'], styles['h2']),
         _trend_block(audit, styles, palette)],
        palette))

    story.append(NextPageTemplate('body'))
    story.append(PageBreak())

    # ---------------- Corrective actions ----------------
    actions = list(audit.corrective_actions.all())
    if actions or audit.has_critical_failure:
        story.append(Paragraph('CORRECTIVE ACTIONS (%d)' % len(actions), styles['h2']))
        story.append(HRFlowable(width='100%', thickness=1.2, color=palette['primary'],
                                spaceBefore=2, spaceAfter=8))
        if audit.has_critical_failure:
            story.append(Paragraph('<font color="%s"><b>\u26A0 Critical Failures</b></font>'
                                   % palette['bad'], styles['body']))
            for sec in audit.audit_sections.all():
                for resp in sec.responses.all():
                    if (resp.is_answered and resp.question.is_critical
                            and resp.scored_points == 0 and not resp.is_na):
                        txt = str(resp.question.question_text)
                        if resp.comments:
                            txt += ' \u2014 %s' % str(resp.comments)
                        story.append(Paragraph('\u2022 %s' % txt, styles['muted']))
                        story.append(Spacer(1, 3))
            story.append(Spacer(1, 8))
        else:
            story.append(Paragraph(
                '<font color="%s"><b>\u2713 All critical standards met.</b></font>'
                % palette['good'], styles['body']))
            story.append(Spacer(1, 6))
        story.extend(_corrective_action_flows(actions, palette, styles))
        story.append(Spacer(1, 8))

    # ---------------- Question sections ----------------
    for idx, sec in enumerate(audit.audit_sections.all(), start=1):
        story.append(_section_header(sec, idx, palette))
        story.append(Spacer(1, 4))
        if sec.section.description:
            story.append(Paragraph(str(sec.section.description), styles['muted']))
            story.append(Spacer(1, 4))
        if sec.has_critical_failure:
            story.append(Paragraph(
                '<font color="%s"><b>\u26A0 Critical Failure</b> \u2014 immediate '
                'corrective action required.</font>' % palette['bad'], styles['small']))
            story.append(Spacer(1, 4))
        story.append(_question_table(sec, styles, palette))
        story.append(Spacer(1, 10))

    # ---------------- Signatures ----------------
    story.append(NextPageTemplate('cover'))
    story.append(PageBreak())
    story.append(Paragraph('SIGNATURES', styles['h2']))
    story.append(HRFlowable(width='100%', thickness=1.2, color=palette['primary'],
                            spaceBefore=2, spaceAfter=14))
    auditor = ((audit.auditor.get_full_name() or audit.auditor.username)
               if audit.auditor else '')
    auditor_name = audit.auditor_signature or auditor
    manager_name = audit.auditee_signature or audit.manager_on_duty
    sig_t = Table([
        [Paragraph('AUDITOR', styles['sig-label']),
         Paragraph('MANAGER', styles['sig-label'])],
        [Paragraph('<br/><br/><br/><br/>%s' % auditor_name, styles['sig-name']),
         Paragraph('<br/><br/><br/><br/>%s' % manager_name, styles['sig-name'])],
        [Paragraph('Auditor', styles['sig-role']), Paragraph('Manager on Duty', styles['sig-role'])],
    ], colWidths=[(PAGE_W - 2 * MARGIN - 20) / 2, (PAGE_W - 2 * MARGIN - 20) / 2])
    sig_t.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (1, 0), 0.6, palette['faint']),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(sig_t)

    doc.build(story)
    return target


def generate_pdf(audit, summary, business, critical_fail_count=0, target=None):
    """Generate the audit PDF. target may be None (returns bytes) or a path/file."""
    if target is None:
        from io import BytesIO
        buf = BytesIO()
        build_document(audit, summary, business, critical_fail_count, buf)
        return buf.getvalue()
    return build_document(audit, summary, business, critical_fail_count, target)
