import { money, words, Empty, Metric } from './components';
import MetricHelp from './MetricHelp';
import { percent } from './DecisionReport';

export default function CurrentMonitoring({ data }: { data: any }) {
  const d = data.decisions, o = data.operations, out = data.outcomes;
  return <>
    <div className="current-scope">
      <strong>Recorded under Policy v{data.policy.version}</strong>
      <span>All active periods of this saved version. Proposals and other versions are excluded.</span>
    </div>
    <div className="decision-stats">
      <Metric
        label="Final decisions"
        value={String(d.total)}
        detail={`${d.human} by reviewers · ${d.automatic} automatic`}
      />
      <Metric
        label="Executed automation share"
        value={percent(o.automation_rate)}
        detail={`${d.automatic} / ${d.total} final decisions`}
      />
      <Metric
        label="Simulated refunds paid"
        value={money(d.paid_cents)}
        detail={`${d.payment_count} ledger payments, including human approvals`}
      />
      <Metric
        label="Follow-up recorded"
        value={d.total ? `${out.recorded_cases} / ${d.total}` : 'No decisions yet'}
        detail={`${out.missing_cases} decisions without any outcome record`}
      />
    </div>
    {
      !d.total ?
        <Empty
          title="No decisions recorded under this version yet"
          detail="Queue routing shows proposals. Executed refunds, reviewer decisions and subsequent outcomes will appear here as they are recorded."
        /> :
        <>
          <div className="decision-two">
            <section className="decision-block">
              <h3>Final decisions</h3>
              <dl className="decision-definitions">
                {
                  [['approved', 'Full refund'], ['partial', 'Partial refund'], ['rejected', 'Rejected']].map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{o.decision_types[key] || 0}</dd></div>)
                }
              </dl>
            </section>
            <section className="decision-block">
              <h3>Human review of Auto Approve proposals</h3>
              {
                o.reference_auto_count ?
                  <>
                    <dl className="decision-definitions">
                      <div><dt>Proposals reviewed by a person</dt><dd>{o.reference_auto_count}</dd></div>
                      <div>
                        <dt>Proposed more than the human decision</dt>
                        <dd>{o.reference_excess_cases} / {o.reference_auto_count}</dd>
                      </div>
                      <div><dt>Amount above human decisions</dt><dd>{money(o.reference_excess_cents)}</dd></div>
                    </dl>
                    <p className="small muted">Uses the proposal captured at decision time. Disagreement is not proven loss; automatic payments are
                      not their own reference.</p>
                  </> :
                  <p>No human-reviewed Auto Approve proposals yet. Executed automatic refunds do not provide independent
                    validation.</p>
              }
            </section>
          </div>
          <section className="decision-block">
            <h3>Recorded follow-up</h3>
            <p className="small muted">
              {out.recorded_cases} of {d.total} decided requests have at least one follow-up record. Missing follow-up remains unknown, regardless
              of age.</p>
            <div className="table-scroll">
              <table>
                <thead><tr><th>Event</th><th>Distinct requests</th><th>Event records</th></tr></thead>
                <tbody>
                  {
                    ['chargeback', 'appeal', 'audit_pass', 'audit_fail'].map(key => <tr key={key}>
                      <th>{words(key)}</th>
                      <td>{out.case_counts[key] || 0}</td>
                      <td>{out.event_counts[key] || 0}</td>
                    </tr>)
                  }
                </tbody>
              </table>
            </div>
            <p className="small muted">Requests may have several events. Zero recorded chargebacks does not establish zero risk. Chargeback
              rates and total losses need complete follow-up and order amounts.</p>
          </section>
          <details className="decision-block">
            <summary>Outcomes by deciding rule</summary>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Rule or policy check</th>
                    <th>Decisions</th>
                    <th><MetricHelp label="Overrides" /></th>
                    <th>Without follow-up</th>
                    <th>Chargeback or failed audit</th>
                  </tr>
                </thead>
                <tbody>
                  {
                    data.feedback.map((g: any) => <tr key={g.rule_id}>
                      <th>{g.rule_name || words(g.rule_id)}</th>
                      <td>{g.decisions}</td>
                      <td>{g.overrides}</td>
                      <td>{g.unknown_outcomes}</td>
                      <td>{g.adverse}</td>
                    </tr>)
                  }
                </tbody>
              </table>
            </div>
            <p className="small muted">Attribution to the rule captured at decision time. Counts describe recorded results; they do not measure
              each rule’s causal effect.</p>
          </details>
          <details className="decision-block">
            <summary>Decision volume by day</summary>
            <p className="small muted">UTC decision date. Days without decisions are omitted.</p>
            <div className="table-scroll">
              <table>
                <thead><tr><th>Date</th><th>Human</th><th>Automatic</th><th>Simulated refunds paid</th></tr></thead>
                <tbody>
                  {
                    o.daily.map((day: any) => <tr key={day.date}>
                      <th>{day.date}</th>
                      <td>{day.human}</td>
                      <td>{day.automatic}</td>
                      <td>{money(day.paid_cents)}</td>
                    </tr>)
                  }
                </tbody>
              </table>
            </div>
          </details>
        </>
    }
    <details className="decision-block">
      <summary>What this page can and cannot measure</summary>
      <p>These are observed operating records for Current, not a comparison or forecast. Use Backtest and Shadow
        to compare policies.</p>
      <p>Active reviewer time, customer satisfaction, complete chargeback losses and causal savings are not captured.
        AI calls serve the whole workspace and cannot be attributed to Current.</p>
    </details>
  </>;
}
