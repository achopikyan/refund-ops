export const configGroups: [string, [string, string, string?][]][] = [
  [
    'Release evidence',
    [
      ['min_prospective_auto', 'New automatic proposals'],
      ['min_changed_cases', 'Changed new-arrival requests'],
      ['min_shadow_hours', 'Minimum Shadow hours'],
      ['max_error_bps', 'Maximum 95% upper estimate (%)', 'percent'],
      ['projection_cases', 'Future approvals in risk scenario'],
      ['max_projected_loss_cents', 'Maximum future exposure scenario (USD)', 'dollars']
    ]
  ],
  [
    'Cost assumptions',
    [
      ['hourly_cost_cents', 'Reviewer hourly cost (USD)', 'dollars'],
      ['review_minutes', 'Minutes per manual review'],
      ['ai_cost_cents', 'AI cost per case (USD)', 'dollars'],
      ['audit_cost_cents', 'Cost per future audit (USD)', 'dollars'],
      ['audit_fraction', 'Future audit fraction (0-1)']
    ]
  ],
];

