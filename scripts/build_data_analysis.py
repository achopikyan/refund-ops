"""Data analysis of the supplied CSVs: deliverables/data-analysis.pdf.

Every figure is computed from data/history.csv and data/pending.csv, except the policy replay,
which quotes the application's Backtest (README.md). Needs reportlab and matplotlib:
python scripts/build_data_analysis.py
"""
from collections import Counter
import csv
import io
from pathlib import Path
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
INK, GRAY, LINE = '#183F35', '#52655E', '#93ABA0'
GREEN, BLUE, AMBER, RED, PURPLE, CHART = '#DBEEE4', '#E1ECF8', '#F6EBCF', '#F5E0E3', '#EAE5F5', '#3B7A63'
FRAUD = {'yes': True, 'y': True, 'true': True, 'no': False, 'n': False, 'false': False}
REASONS = {'changed mind': 'changed_mind', 'damaged': 'arrived_damaged', 'arrived damaged': 'arrived_damaged',
           'late': 'late_delivery', 'wrong item': 'wrong_item'}
LABELS = {'never_arrived': 'Never arrived', 'arrived_damaged': 'Arrived damaged', 'wrong_item': 'Wrong item',
          'late_delivery': 'Late delivery', 'changed_mind': 'Changed mind', 'wrong_size': 'Wrong size'}
# What the notes already said before each approval that was later charged back.
CHARGEBACK_EVIDENCE = {
    'RF-1005': 'Carrier proof of delivery, signed for at the address.',
    'RF-2042': 'Tracking shows delivered and signed.',
    'RF-1045': 'Customer told support the parcel did arrive, late.',
    'RF-2083': 'Customer said the item broke during self-assembly.',
    'RF-1027': 'Photos show the original packaging still sealed.',
    'RF-2111': 'Fraud flag, new account, no photos after two requests.',
    'RF-1065': 'Fraud flag, new account, first order, no photos.',
    'RF-2074': 'No notes; inside the old rule\'s limits.',
}


def number(value):
    try: return float(value)
    except ValueError: return None


def load(name):
    rows, seen = [], set()
    for raw in csv.DictReader(open(ROOT / 'data' / name, encoding='utf-8-sig')):
        key = tuple(raw.values())
        if key in seen: continue
        seen.add(key)
        r = dict(raw)
        r['amount'] = float(re.sub(r'USD|\$|,|\s', '', r['amount_usd']))
        r['tenure'], r['prior'], r['days'] = (number(r[k]) for k in ('tenure_months', 'prior_refunds_12m', 'days_since_delivery'))
        r['fraud'] = FRAUD.get(r['fraud_flag'].strip().lower())
        r['reason'] = REASONS.get(r['stated_reason'], r['stated_reason'])
        r['minutes'] = number(r.get('review_minutes') or '') or 0
        r['auto'] = r.get('decided_by') == 'auto'
        r['outcome'] = (r.get('outcome_note') or '').lower()
        rows.append(r)
    return rows


def old_rule(r):
    window = r['reason'] != 'changed_mind' or (r['days'] is not None and r['days'] <= 14)
    return r['amount'] < 55 and r['tenure'] is not None and r['tenure'] >= 9 and r['prior'] == 0 and r['fraud'] is False and window


def money(v): return f'${v:,.0f}' if v == int(v) else f'${v:,.2f}'


def analyse():
    raw = list(csv.DictReader(open(ROOT / 'data/history.csv', encoding='utf-8-sig')))
    pending_raw = list(csv.DictReader(open(ROOT / 'data/pending.csv', encoding='utf-8-sig')))
    h, pending = load('history.csv'), load('pending.csv')
    staff = [r for r in h if not r['auto']]
    approved = [r for r in h if r['decision'] == 'approved']
    chargebacks = [r for r in h if 'chargeback' in r['outcome']]
    eligible = [r for r in h if r['tenure'] is not None and r['days'] is not None and r['days'] >= 0 and r['fraud'] is not None]
    # As in the application's chargeback context: approved or partial refunds, without rows that have data errors.
    refunded = [r for r in h if r['decision'] in ('approved', 'partial') and not (r['days'] is not None and r['days'] < 0)]
    cohort = lambda keep: (sum('chargeback' in r['outcome'] for r in refunded if keep(r)), sum(keep(r) for r in refunded))
    a = {
        'raw': len(raw), 'unique': len(h), 'pending_raw': len(pending_raw), 'pending_ids': len({r['request_id'] for r in pending}),
        'start': min(r['requested_at'] for r in h if re.fullmatch(r'\d{4}-\d{2}-\d{2}', r['requested_at'])),
        'end': max(r['requested_at'] for r in h if re.fullmatch(r'\d{4}-\d{2}-\d{2}', r['requested_at'])),
        'web': sum(r['request_id'].startswith('RF-1') for r in h), 'desk': sum(r['request_id'].startswith('RF-2') for r in h),
        'auto': sum(r['auto'] for r in h), 'staff': len(staff), 'reviewers': len({r['decided_by'] for r in staff}),
        'decisions': Counter(r['decision'] for r in h), 'staff_decisions': Counter(r['decision'] for r in staff),
        'minutes': sum(r['minutes'] for r in staff),
        'by_reason': {k: (sum(r['reason'] == k for r in staff), sum(r['minutes'] for r in staff if r['reason'] == k),
                          sum(r['reason'] == k for r in h if r['auto'])) for k in LABELS},
        'paid_auto': sum(r['amount'] for r in approved if r['auto']), 'paid_staff': sum(r['amount'] for r in approved if not r['auto']),
        'chargebacks': chargebacks, 'unknown': sum(not r['outcome'] for r in h),
        'late_change': [r for r in h if r['reason'] == 'changed_mind' and (r['days'] or 0) > 14 and r['decision'] in ('approved', 'partial')],
        'window_rejected': sum('outside 14 day window' in r['outcome'] for r in h),
        'appeals': [r for r in h if 'appeal' in r['outcome']],
        'no_photo': [r for r in h if r['auto'] and r['reason'] == 'arrived_damaged' and r['amount'] > 50],
        'flagged': [r for r in h if r['fraud']], 'confirmed': [r for r in h if 'fraud team confirmed' in r['outcome']],
        'eligible': len(eligible), 'fit': sum(old_rule(r) == r['auto'] for r in eligible),
        'misfit': [r['request_id'] for r in eligible if old_rule(r) != r['auto']],
        'cohorts': [('Requested amount at most $50', cohort(lambda r: r['amount'] <= 50)),
                    ('Over $50 through $100', cohort(lambda r: 50 < r['amount'] <= 100)),
                    ('Over $100 through $200', cohort(lambda r: 100 < r['amount'] <= 200)),
                    ('Over $200 through $300', cohort(lambda r: 200 < r['amount'] <= 300)),
                    ('Over $300', cohort(lambda r: r['amount'] > 300)),
                    ('Customer tenure at least 24 months', cohort(lambda r: (r['tenure'] or 0) >= 24))],
        'old_pending': [r for r in pending if old_rule(r) and r['request_id'] != 'RF-2183'],
        'amount_formats': [r['amount_usd'] for r in raw if not re.fullmatch(r'\d+(\.\d+)?', r['amount_usd'].strip())],
        'dates': [r['requested_at'] for r in raw + pending_raw if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', r['requested_at'])],
        'flags': Counter(r['fraud_flag'] for r in raw),
        'reason_variants': sorted({r['stated_reason'] for r in raw} - set(LABELS)),
        'category_variants': sorted({r['category'] for r in raw} - {'apparel', 'home', 'electronics'}),
    }
    a['excluded'] = a['unique'] - a['eligible']
    return a


def chart(draw, height=2.6):
    plt.rcParams.update({'font.family': ['Arial', 'Helvetica', 'DejaVu Sans'], 'font.size': 9, 'axes.edgecolor': LINE,
                         'axes.labelcolor': GRAY, 'xtick.color': GRAY, 'ytick.color': GRAY})
    fig, ax = plt.subplots(figsize=(6.6, height), dpi=220)
    draw(ax)
    for side in ('top', 'right'): ax.spines[side].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format='png'); plt.close(fig); buf.seek(0)
    return Image(buf, width=170 * mm, height=170 * mm * height / 6.6)


def minutes_chart(a):
    order = sorted(LABELS, key=lambda k: a['by_reason'][k][1])
    def draw(ax):
        values = [a['by_reason'][k][1] for k in order]
        bars = ax.barh([LABELS[k] for k in order], values, color=CHART, height=0.62)
        for bar, k in zip(bars, order):
            cases, minutes, _ = a['by_reason'][k]
            ax.text(bar.get_width() + 6, bar.get_y() + bar.get_height() / 2,
                    f'{minutes:g} min · {cases} cases · {minutes / cases:.1f} min each', va='center', color=INK, fontsize=8.5)
        ax.set_xlim(0, max(values) * 1.75); ax.set_xlabel('Recorded reviewer minutes, staff decisions')
        ax.xaxis.grid(True, color='#D9E2DD', linewidth=0.6); ax.set_axisbelow(True)
    return chart(draw)


def deciders_chart(a):
    order = sorted(LABELS, key=lambda k: a['by_reason'][k][0] + a['by_reason'][k][2])
    def draw(ax):
        labels = [LABELS[k] for k in order]
        auto = [a['by_reason'][k][2] for k in order]; staff = [a['by_reason'][k][0] for k in order]
        ax.barh(labels, auto, color=CHART, height=0.62, label='Old auto rule')
        ax.barh(labels, staff, left=auto, color='#C9A15A', height=0.62, label='Reviewers')
        for i, (x, y) in enumerate(zip(auto, staff)):
            ax.text(x / 2, i, str(x), va='center', ha='center', color='white', fontsize=8, fontweight='bold')
            ax.text(x + y / 2, i, str(y), va='center', ha='center', color=INK, fontsize=8, fontweight='bold')
        ax.set_xlabel('Historical requests by stated reason'); ax.legend(frameon=False, loc='lower right', fontsize=8.5)
    return chart(draw, 2.4)


def build(a):
    out = ROOT / 'deliverables/data-analysis.pdf'
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                            title='Refund history: data analysis', author='achopikyan', creator='achopikyan',
                            subject='Analysis of the supplied refund history and pending queue')
    base = ParagraphStyle('base', fontName='Helvetica', fontSize=9.6, leading=13.4, textColor=colors.HexColor(GRAY), alignment=TA_LEFT, spaceAfter=5)
    body = ParagraphStyle('body', base, textColor=colors.HexColor('#24342F'))
    h1 = ParagraphStyle('h1', base, fontName='Helvetica-Bold', fontSize=21, leading=25, textColor=colors.HexColor(INK), spaceAfter=4)
    h2 = ParagraphStyle('h2', base, fontName='Helvetica-Bold', fontSize=13, leading=17, textColor=colors.HexColor(INK), spaceBefore=10, spaceAfter=4, keepWithNext=1)
    small = ParagraphStyle('small', base, fontSize=8.2, leading=11)
    cell = ParagraphStyle('cell', base, fontSize=8.6, leading=11.2, spaceAfter=0, textColor=colors.HexColor('#24342F'))
    head = ParagraphStyle('head', cell, fontName='Helvetica-Bold', textColor=colors.HexColor(INK))
    bullet = ParagraphStyle('bullet', body, leftIndent=11, bulletIndent=0, spaceAfter=3)

    def table(rows, widths, fill=BLUE, align_right=()):
        data = [[Paragraph(str(c), head if i == 0 else cell) for c in row] for i, row in enumerate(rows)]
        t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
        style = [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(fill)), ('LINEBELOW', (0, 0), (-1, -1), 0.4, colors.HexColor(LINE)),
                 ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 3.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5)]
        t.setStyle(TableStyle(style))
        for col in align_right:
            for row in data: row[col].style = ParagraphStyle('r', row[col].style, alignment=2)
        return t

    def bullets(items): return [Paragraph(x, bullet, bulletText='•') for x in items]

    cb, d = a['chargebacks'], a['decisions']
    cb_total, fees = sum(r['amount'] for r in cb), 25 * len(cb)
    staff_cb = [r for r in cb if not r['auto']]
    late = a['late_change']
    story = [
        Paragraph('Refund history: what the data shows', h1),
        Paragraph(f"achopikyan · analysis of <font face='Courier'>data/history.csv</font> ({a['raw']} rows, {a['unique']} unique requests, "
                  f"{a['start'][8:].lstrip('0')} June to {a['end'][8:].lstrip('0')} August 2026) and <font face='Courier'>data/pending.csv</font> "
                  f"({a['pending_raw']} rows, {a['pending_ids']} requests). Counts are recorded observations, not causal estimates.", base),
        Spacer(1, 4),
        Table([[Paragraph('<b>Key findings</b>', head)], *[[p] for p in bullets([
            f"Reviewers recorded <b>{a['minutes']:,.0f} minutes</b> on {a['staff']} requests. Never-arrived claims took the most time; wrong-size returns the least.",
            f"<b>{len(cb)} approvals ended in a chargeback</b>: {money(cb_total)} refunded plus {money(fees)} in fees. "
            f"{len(staff_cb)} were reviewer approvals made against evidence already in the notes.",
            f"Decisions are inconsistent: {len(late)} change-of-mind refunds were approved after the 14-day limit, all by one reviewer, while "
            f"{a['window_rejected']} others were refused for the same reason. {len(a['appeals'])} rejections were overturned on appeal.",
            f"The old rule is <b>amount below $55, tenure at least 9 months, no prior refunds, clear fraud flag</b> and the 14-day window. "
            f"It explains {a['fit']} of {a['eligible']} decidable requests, and it never reads notes.",
            f"Only {a['unique'] - a['unknown']} of {a['unique']} requests have a recorded outcome, so no approach can claim a measured error rate yet.",
        ])]], colWidths=[170 * mm], style=TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(GREEN)),
                                                      ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
                                                      ('TOPPADDING', (0, 0), (0, 0), 7), ('BOTTOMPADDING', (0, -1), (-1, -1), 6)])),

        Paragraph('1. The sample', h2),
        table([['Measure', 'Value'],
               ['Unique historical requests', f"{a['unique']} ({a['raw'] - a['unique']} exact duplicate rows removed)"],
               ['Channel', f"{a['web']} web form (RF-1xxx) · {a['desk']} support desk (RF-2xxx)"],
               ['Decided by', f"old auto rule {a['auto']} · {a['reviewers']} reviewers {a['staff']}"],
               ['Decisions', f"{d['approved']} approved · {d['partial']} partial · {d['rejected']} rejected; the old rule only approves"],
               ['Approved dollars', f"old rule {money(a['paid_auto'])} · reviewers {money(a['paid_staff'])}, plus {d['partial']} partial refunds"],
               ['Recorded outcomes', f"{a['unique'] - a['unknown']} of {a['unique']}; {a['unknown']} blank"]], [52, 118]),

        Paragraph('2. Where reviewer time goes', h2),
        Paragraph('The brief says most staff reviews do not need to be read. The time data supports that: simple returns take a few minutes, '
                  'while delivery disputes and late deliveries take ten or more, because they need evidence weighed against policy note 4.', body),
        minutes_chart(a),
        KeepTogether([Paragraph('The old rule already takes most wrong-size and change-of-mind requests; reviewers spend their time on disputes and damage:', body),
                      deciders_chart(a)]),
    ]
    story += [
        Paragraph('3. Where money goes: chargebacks', h2),
        Paragraph(f"Policy note 7: every chargeback costs the order amount plus a $25 fee. The refund amount stands in for the missing order amount. "
                  f"{len(staff_cb)} of {len(cb)} chargebacks followed a reviewer approval where the notes already pointed the other way:", body),
        table([['Request', 'Refund', 'Reason', 'Approved by', 'What the notes already said'],
               *[[r['request_id'], money(r['amount']), LABELS[r['reason']], 'Old rule' if r['auto'] else 'Reviewer', CHARGEBACK_EVIDENCE[r['request_id']]]
                 for r in sorted(cb, key=lambda r: (r['auto'], -r['amount']))],
               ['Total', money(cb_total), '', '', f"plus {money(fees)} in fees: {money(cb_total + fees)}"]],
              [20, 17, 27, 22, 84], RED, align_right=(1,)),
        Spacer(1, 4),
        Paragraph('Recorded chargebacks among approved or partial refunds, excluding one row with invalid data. These are counts, not calibrated '
                  'rates: most outcomes are unknown and the groups are small.', body),
        table([['Refunded cohort', 'Chargebacks / refunds'], *[[name, f'{n} / {total}'] for name, (n, total) in a['cohorts']]], [110, 60], BLUE, align_right=(1,)),

        Paragraph('4. Where decisions break', h2),
        *bullets([
            f"<b>Change of mind after 14 days.</b> Note 2 says <i>no exceptions</i>, yet {len(late)} requests were approved "
            f"{min(r['days'] for r in late):.0f}–{max(r['days'] for r in late):.0f} days after delivery ({', '.join(r['request_id'] for r in late)}), all by "
            f"one reviewer. {a['window_rejected']} others were refused as outside the window.",
            f"<b>Appeals.</b> {', '.join(r['request_id'] for r in a['appeals'])} were rejected and then refunded in full on appeal; one customer closed "
            "their account and one turned out to be a confirmed picking error, which note 6 refunds with no questions asked.",
            f"<b>Damage without a photo.</b> Note 3 requires a photo above $50, but the old rule approved "
            f"{len(a['no_photo'])} damage claims of {money(min(r['amount'] for r in a['no_photo']))}–{money(max(r['amount'] for r in a['no_photo']))} "
            f"({', '.join(r['request_id'] for r in a['no_photo'])}) with no photo in the notes.",
            f"<b>Fraud confirmation arrives later.</b> {len(a['flagged'])} requests carried a fraud flag. For {len(a['confirmed'])}, the outcome note says "
            "the fraud team confirmed the card was stolen, after the refund decision. A rule that pays only confirmed stolen-card cases therefore matches "
            "none of them at decision time, which the Backtest shows.",
        ]),

        Paragraph('5. The old rule, reconstructed', h2),
        Paragraph(f"Policy note 1: <i>small stuff from good customers goes through automatically; IT set that up last year.</i> Searching the "
                  f"historical routing gives amount below $55, tenure at least 9 months, no prior refunds, a clear fraud flag and the 14-day change-of-mind "
                  f"window. It matches {a['fit']} of {a['eligible']} requests with complete data; the exception is {', '.join(a['misfit'])}. "
                  f"{a['excluded']} rows with missing tenure or delivery days, negative days or a blank fraud flag are left out.", body),
        Paragraph(f"Applied to the pending queue, the same rule pays {len(a['old_pending'])} requests totalling "
                  f"{money(sum(r['amount'] for r in a['old_pending']))} ({', '.join(r['request_id'] for r in a['old_pending'])}). It cannot see that "
                  "RF-1074's note (in Spanish) says the store already refunded the customer, that RF-1075 is a change of mind on day 22 filed as damage, "
                  "or that RF-2196, RF-2198 and RF-2200 are caught in a Northfield carrier disruption.", body),

        Paragraph('6. Messy data and how the application handles it', h2),
        table([['Issue', 'In the files', 'Handling'],
               ['Duplicates', f"{a['raw'] - a['unique']} exact duplicate history rows; RF-2183 appears twice in pending at $49 and $52",
                'Exact duplicates collapse; conflicting versions are kept and must be reconciled before approval'],
               ['Amount formats', ', '.join(a['amount_formats']), 'Parsed to integer cents'],
               ['Dates', f"{len(a['dates'])} non-ISO dates, day-first and ISO timestamps", 'Day-first by default, with a visible warning; timestamps reduced to dates'],
               ['Fraud flag', ' · '.join(f"{k or 'blank'} {v}" for k, v in sorted(a['flags'].items(), key=lambda x: -x[1])),
                'yes/Y/true and no/N/false normalized; blank stays unknown and cannot pass a fraud-flag condition'],
               ['Reason and category', ', '.join(a['reason_variants'] + a['category_variants']), 'Aliases normalized to the dictionary values'],
               ['Missing or invalid numbers', 'Tenure missing twice; delivery days missing once and negative once',
                'Unknown values never satisfy a rule; negative days are a data error that sends the request for information'],
               ['Reason contradicts notes', 'For example RF-1075: damage selected, note says it is fine', 'The LLM flags the conflict with a quote; the request goes to Review']],
              [32, 66, 72], AMBER),

        *[KeepTogether([Paragraph('7. What this means for the line', h2), *bullets([
            'Automate the cases that were cheap and safe in history (simple returns, small damage with a photo, confirmed merchant or fraud-team outcomes), '
            'and keep prior refunds, delivery disputes, electronics damage and anything over $300 with a person.',
            'Read the notes. Every chargeback above and most broken decisions were visible in the free text, which is why evidence extraction uses an LLM '
            'with exact quotes while the rules and payments stay in code.',
            'Test every change against this history before it goes live. On the same 248 requests, the application\'s Backtest gives:',
        ]),
        table([['Version', 'Automatic', 'Proposed refunds', 'Above human amount', 'Known chargebacks on automatic'],
               ['v1 (old rule)', '108', '$3,332.51', '$0 on 1 assessed', '1'],
               ['v2 (proposed)', '108', '$4,430', '$0 on 32 assessed', '0'],
               ['v3 (broader)', '125', '$6,681.45', '$415 in 3 of 44 assessed', '0']], [32, 24, 32, 44, 38], GREEN, align_right=(1, 2, 4)),
        Spacer(1, 4),
        Paragraph(f"Limits: {a['unknown']} of {a['unique']} outcomes are blank, historical decisions can be wrong, the pending queue was inspected during "
                  "development and is not a blind holdout, and refund amounts stand in for order amounts. Zero observed excess is not proof of safety.", small)])],
    ]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out


def footer(canvas, doc):
    canvas.saveState(); canvas.setFont('Helvetica', 7.5); canvas.setFillColor(colors.HexColor(GRAY))
    canvas.drawString(20 * mm, 10 * mm, 'Refund operations · data analysis')
    canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, str(doc.page)); canvas.restoreState()


if __name__ == '__main__':
    print(f'Wrote {build(analyse()).relative_to(ROOT)}')
