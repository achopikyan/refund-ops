import { money, Metric } from './components';
import { percent } from './DecisionReport';

// Standalone policy metrics: no baseline deltas or implied causal savings.
export default function PolicyEconomics({ report: r }: { report: any }) {
  const b = r.candidate, a = r.money.assumptions;
  const manual = b.routes.review + b.routes.fraud;
  const minutes = manual * a.review_minutes;
  const auditCount = b.auto_count * a.audit_fraction;
  return <>
    <div className="decision-stats">
      <Metric
        label="Automatic proposed refunds"
        value={money(b.payout_cents)}
        detail={`${b.auto_count} Auto Approve proposals; no payments made by this test`}
      />
      <Metric
        label="Without eligible reference"
        value={money(b.unreviewed_cents)}
        detail={`${b.unreviewed_auto} automatic proposals with unknown reference amount`}
      />
      <Metric
        label="Above human reference"
        value={b.reviewed_auto ? money(b.overpayment_cents) : 'Unknown'}
        detail={`${b.overpayment_cases} / ${b.reviewed_auto} referenced proposals; disagreement, not proven loss`}
      />
      <Metric
        label="Future overpayment stress"
        value={money(r.money.stress_loss_cents)}
        detail={`${a.projection_cases} approvals × ${money(a.max_single_cents)} cap × upper group error bound`}
      />
    </div>
    <div className="decision-two">
      <section className="decision-block">
        <h3>Review workload</h3>
        <dl className="decision-definitions">
          <div><dt>Review</dt><dd>{b.routes.review}</dd></div>
          <div><dt>Fraud Review</dt><dd>{b.routes.fraud}</dd></div>
          <div><dt>Manual routes with full-approval reference</dt><dd>{b.manual_full_approvals}</dd></div>
          <div><dt>Review time · scenario</dt><dd>{minutes.toFixed(1)} min</dd></div>
          <div>
            <dt>Review cost · scenario</dt>
            <dd>{money(Math.round(minutes / 60 * a.hourly_cost_cents))}</dd>
          </div>
        </dl>
        <p className="small muted">
          {a.review_minutes} minutes per manual route at {money(a.hourly_cost_cents)}/hour. Specialist effort, customer waiting and active reviewer time are not measured. Full human approval
          does not prove a case was safe to automate.</p>
      </section>
      <section className="decision-block">
        <h3>Processing assumptions</h3>
        <dl className="decision-definitions">
          <div><dt>Extraction · scenario</dt><dd>{money(r.quality.total * a.ai_cost_cents)}</dd></div>
          <div><dt>Audit · scenario</dt><dd>{money(Math.round(auditCount * a.audit_cost_cents))}</dd></div>
          <div><dt>Audit fraction of automatic proposals</dt><dd>{percent(a.audit_fraction)}</dd></div>
          <div><dt>Single-payment cap</dt><dd>{money(a.max_single_cents)}</dd></div>
          <div><dt>Proposals above cap</dt><dd>{b.cap_exceedances}</dd></div>
        </dl>
        <p className="small muted">Assumes one extraction per request at {money(a.ai_cost_cents)}, and {money(a.audit_cost_cents)} per sampled audit. These are scenario costs, not billed totals. Retries and specialist costs are not
          included.</p>
      </section>
    </div>
    <p className="decision-notice">The test makes no payments. Actual losses, avoided chargebacks and causal ROI cannot be inferred from
      proposals or missing outcomes. Use Compare versions for differences between policies.</p>
  </>;
}
