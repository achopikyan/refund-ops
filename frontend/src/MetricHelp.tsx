import { UiIcon } from './visualLanguage';

const definitions: Record<string, string> = {
  'Auto Approve': 'Automatic proposals divided by requests in the selected cohort. A larger share reduces routing to people but can increase exposure. It is not an accuracy score.',
  'Review': 'Requests routed to an ordinary reviewer. A decrease can free capacity or remove useful scrutiny; inspect the affected cases.',
  'Fraud Review': 'Requests routed to fraud specialists. More cases can reflect better detection or unnecessary escalations. No confirmed fraud rate is inferred.',
  'Complete evidence': 'Requests whose extraction passed schema, citation and completeness checks, divided by all selected requests. Complete does not mean true. Missing factual answers can remain unknown in a complete extraction.',
  'Net reviewer capacity': 'Review minutes associated with newly automatic cases minus minutes added by cases returned to review. Recorded history and fallback assumptions are identified separately. This is capacity, not proven payroll savings.',
  'Net reviewer minutes · scenario': 'Minutes freed minus minutes added compared with Current, using recorded durations where available and saved assumptions otherwise.',
  'Above human reference': 'Sum of max(automatic proposed amount minus human reference amount, 0). Only eligible, known references count. This is disagreement with a fallible reference, not realized financial loss.',
  'Excess above reference': 'Potential overpayment compared with an eligible human refund amount. The denominator and missing references matter; never compare amounts from different cohorts.',
  'Error upper bound · 95%': 'From fully reviewed customer groups, estimate how large the share with any proposal above the human decision could still be. This is a one-sided 95% statistical bound, not a prediction. It assumes independent, representative groups; a small sample remains uncertain even with no observed excess.',
  'Upper group error rate · 95%': 'Upper estimate for the share of customer groups with any proposal above a human decision, using a 95% statistical bound. It is not a chargeback probability. Zero observed differences in a small sample does not establish zero risk.',
  'Exact amount agreement': 'Automatic proposals exactly equal to the reference amount divided by comparable automatic proposals. Human and historical decisions can be wrong, so agreement is not accuracy.',
  'Eligible references': 'Historical human decisions with known refund amounts, or same-input Shadow judgments recorded after prediction. Historical auto decisions, unknown partial amounts and late judgments cannot establish safety.',
  'Automatic reference coverage': 'Automatic proposals with eligible known human reference amounts divided by all automatic proposals. Monetary coverage is also shown; high count coverage can still leave large amounts unreviewed.',
  'Critical findings': 'Recorded critical violations. Zero recorded findings is not evidence that every possible failure was checked.',
  'New automatic proposals': 'Cases sent to a person by Current but automatically proposed by the candidate. Inspect this expansion separately from already-automatic cases.',
  'Returned to a reviewer': 'Cases automatic under Current but manual under the candidate. They add workload and may reduce unsafe proposals. Routing to a person does not prove a loss was prevented.',
  'Reason or rule changes only': 'Same route and automatic amount, but a different deciding rule or explanation. Useful for traceability; these are not additional automated cases.',
  'Automatic amount changes': 'Same route but a different proposed automatic amount. Route-only comparisons would miss this monetary change.',
  'Operating margin change': 'Priced net reviewer capacity minus incremental extraction and audit costs. Shared extraction cancels. Excludes unmeasured customer effects and does not establish causal ROI.',
  'Operating margin change · scenario': 'Scenario based on saved costs. Positive and negative values describe a monetary trade-off, not a policy recommendation.',
  'Automatic proposed money': 'Sum of candidate automatic refund proposals. It is potential cash exposure, not paid money or expected loss.',
  'Future overpayment stress': 'Upper customer-group excess bound × projected future approvals × per-payment cap. A stress scenario under representativeness assumptions, not a guaranteed loss ceiling.',
  'Future stress · saved assumptions': 'Each version uses its saved projection size, error bound and payment cap. Different assumptions can change this value even when routing is similar.',
  'New-auto break-even error rate': 'Fraction of newly automatic proposals that could lose their full proposed amount before their modeled review benefit is exhausted. An illustrative threshold, not an estimated error probability.',
  'Chargeback probability / causal ROI': 'Not estimable from incomplete follow-up and nonrandom Shadow routing. No missing outcome is treated as success.',
  'Chargeback rate / full loss': 'Full order amount and complete follow-up are missing. Requested refund amount is not necessarily order amount. Recorded events are counts, not a calibrated rate.',
  'Chargeback fee-only scenario': 'Recorded chargeback cases multiplied by the source-note $25 fee. Excludes unknown order amounts, processor effects and other costs; not booked losses or avoided losses.',
  'Measured causal ROI': 'Requires actual financial outcomes and a suitable counterfactual. Backtest and Shadow alone cannot supply it.',
  'Net against correct-review benchmark': 'Modeled operating margin minus excess on newly automatic cases, available only when every such case has an eligible reference. Assumes the human reference is correct and omits unmeasured harm.',
  'Manual cases with full-approval reference': 'Manual routes whose reference allowed the full requested refund. These are opportunities to investigate, not demonstrated safe automation.',
  'Priced capacity change': 'Net reviewer minutes multiplied by the saved hourly cost. Freed minutes are not automatically a cash saving.',
  'Shared extraction cost': 'Scenario cost of one standard extraction per request, shared by both policies and canceled in the incremental comparison.',
  'Additional candidate extraction': 'Assumes one additional extraction per request if the candidate adds a different question set. Actual cached calls may differ.',
  'Audit cost change': 'Change in automatic proposal count × saved audit fraction × saved audit cost. Negative means less modeled audit work, not necessarily a benefit.',
  'Paired excess change vs Current': 'For the same requests, subtract Current?s total amount above human decisions from the candidate?s total. Negative means less excess proposed; positive means more. This is a comparison with fallible human references, not observed money lost or saved.',
  'Invalid / conflicting inputs': 'Separate counts that can overlap. Invalid fields and conflicting imported versions are not silently omitted from the cohort.',
  'Blocked by extraction': 'Routes blocked by incomplete or unknown evidence. This diagnoses availability and extraction coverage, not policy quality.',
  'Missing customer identity': 'Missing identities prevent independent customer grouping. Such records must not manufacture additional statistical evidence.',
  'Matches': 'Requests satisfying the rule conditions, even if another rule or a policy-wide check determines the outcome.',
  'Decisive': 'Requests whose final result is attributed to this rule. This is winner attribution, not the causal impact of removing the rule.',
  'Overridden': 'Matches superseded by a higher-priority rule or policy-wide check. A zero-win rule may be redundant or protect a rare case absent here.',
  'Unknown': 'Requests where rule conditions cannot be evaluated from available facts. Not equivalent to false.',
  'Overlap': 'Other rules matching the same requests. Counts overlap and must not be summed as unique requests.',
  'Proposed money': 'Automatic proposal amounts, not executed payments. For routing transitions the column is explicitly the requested amount instead.',
  'Requests': 'Count in this selected cohort, including invalid or unresolved cases unless explicitly excluded. The same cohort is used for paired comparisons.',
  'Comparable requests': 'Shared, fresh request intersection for every selected version. Excluded cases remain visible in the overall comparison scope.',
  'Review queue change': 'Candidate Review count minus Current Review count. Positive adds ordinary-review workload; negative removes it. Specialist work is shown separately.',
  'Fraud Review queue change': 'Candidate Fraud Review count minus Current. Positive adds specialist work; negative removes scrutiny. Neither direction by itself establishes quality.',
  '30+ days old': 'Age of recorded decisions, not proof of complete follow-up or a clean outcome. Chargebacks and appeals can arrive later.',
  'Overrides': 'Human decisions differing from a recorded automatic proposal. Disagreement does not establish which decision was correct.',
  'Simulated payments': 'Amounts actually recorded in this local payment ledger under the current saved policy identity. No real payment provider is called.',
  'Recorded decisions': 'Final decisions attributed to this policy identity, across its active periods. Draft and Shadow proposals are excluded.',
  'Ready requests': 'Current open queue eligible for routing. Waiting, on-hold and resolved requests are counted separately.',
};

// Keep API metric names stable while using plain labels in the interface.
const labels: Record<string, string> = {
  'Error upper bound · 95%': 'Upper estimate of affected groups · 95%',
  'Upper group error rate · 95%': 'Upper estimate of affected groups · 95%',
  'New Auto Approve: 95% upper error bound': 'New automation: upper estimate · 95%',
  'Paired excess change vs Current': 'Change in excess amount vs Current',
  'Future overpayment stress': 'Future exposure scenario',
  'Future stress · saved assumptions': 'Future exposure · saved assumptions',
  'New-auto break-even error rate': 'New automation: loss rate that offsets savings',
};

export function metricDefinition(label: string): string {
  if (definitions[label]) return definitions[label];
  if (/unknown outcomes|without an outcome/i.test(label)) return 'No outcome record is available. Missing follow-up remains unknown even for old cases; it cannot count as a successful refund.';
  if (/chargeback/i.test(label)) return 'Recorded chargeback cases in this cohort or routing subgroup. Inspect the cases and follow-up coverage. Routing changes are not proof that chargebacks were prevented.';
  if (/reference coverage|reviewed auto|reviewed proposals|referenced|reviewed customer/i.test(label)) return 'Count of comparable human references with a known amount. Shadow estimates require the same input and a prediction before the judgment; repeated customers are grouped for uncertainty.';
  if (/unreviewed|without eligible reference/i.test(label)) return 'Automatic proposals whose amount has no eligible human reference. The amount is unresolved exposure, not a zero-loss estimate.';
  if (/excess/i.test(label)) return 'Proposed amount above an eligible human reference. Counts and amounts are paired with their denominator; this is disagreement, not confirmed loss.';
  if (/appeal/i.test(label)) return 'Recorded appeal or reversal information. Records may be incomplete; use the underlying note rather than treating a count as a complete customer-outcome rate.';
  if (/time freed|time added|recorded-time|assumed time/i.test(label)) return 'Scenario workload on changed routes. Recorded history and assumed live-review time are separated; active work time, waiting time and specialist effort are not interchangeable.';
  if (/auto.*new|new.*auto/i.test(label)) return 'New automation is the subset moving from human routing under Current to automatic routing under this version. Inspect reference excess and exposure in that subset.';
  if (/95%|upper.*bound/i.test(label)) return definitions['Error upper bound · 95%'];
  if (/cap|limit|requirements|target/i.test(label)) return 'Compared only with the saved manager-configured limit. This is a constraint check, not an overall policy rating.';
  if (/evidence|extraction/i.test(label)) return definitions['Complete evidence'];
  if (/Current|version|baseline/i.test(label)) return 'Paired outputs on the same inputs. Current is a comparison baseline, not a correctness label.';
  if (/amount|money/i.test(label)) return 'Read the stated scope: requested, proposed, referenced and paid amounts are different quantities. Unknown amounts are not zero.';
  return 'Descriptive information for the selected cohort. Inspect its source, denominator and comparison context; no overall policy score or directional recommendation is inferred.';
}

export default function MetricHelp({ label }: { label: string }) {
  const displayed = labels[label] || label;
  return <span className="metric-help-label">
    {displayed}
    <details className="metric-help">
      <summary aria-label={'Explain ' + displayed}><UiIcon name="info" size={14} /></summary>
      <span>{metricDefinition(label)}</span>
    </details>
  </span>;
}
