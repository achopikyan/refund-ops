import { words } from './components';
import type { Rule } from './components';
import { UiIcon, fieldStyle } from './visualLanguage';
import { operators, conditionText, conditionValue } from './policyConditions';
import type { ConditionCatalog } from './policyConditions';

export default function RuleConditions({ rule, catalog, compact = false }: { rule: Rule, catalog: ConditionCatalog, compact?: boolean }) {
  const logic = rule.match === 'all' ? 'AND' : 'OR';
  return <div className="rule-condition-group">
    {
      !compact &&
      <div className="condition-match">
        <UiIcon name={rule.match === 'all' ? 'check' : 'split'} size={13} />
        {
          rule.conditions.length === 1 ?
            'When this matches' :
            rule.match === 'all' ? 'When all conditions match' : 'When any condition matches'
        }
      </div>
    }
    {
      !compact &&
      <div className="condition-column-labels" aria-hidden="true">
        <span>Variable</span>
        <span>Comparison</span>
        <span>Value</span>
      </div>
    }
    <ul className="readable-conditions">
      {
        rule.conditions.map((c, i) => {
          const style = fieldStyle(c.field), op = operators[c.op];
          return <li key={i}>
            {i > 0 && <div className="condition-join"><span>{logic}</span></div>}
            <div className={'readable-condition tone-' + style.tone} aria-label={conditionText(c, catalog)}>
              <span className="readable-variable" title={catalog[c.field]?.label || c.field}>
                <UiIcon name={style.icon} size={15} />
                <span>{catalog[c.field]?.label || words(c.field.replace('facts.', ''))}</span>
              </span>
              <span className="readable-operator">
                <b aria-hidden="true">{op?.symbol || c.op}</b>
                <span>{op?.label || c.op}</span>
              </span>
              <strong className="readable-value">
                {
                  Array.isArray(c.value) ?
                    c.value.map((value, j) => <span className="condition-list-value" key={j}>{conditionValue(c.field, value)}</span>) :
                    conditionValue(c.field, c.value)
                }
              </strong>
            </div>
          </li>
        })
      }
    </ul>
  </div>;
}
