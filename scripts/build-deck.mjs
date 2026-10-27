/** Eight-slide write-up: deliverables/write-up.pptx (editable) and deliverables/write-up.pdf.
 * Needs pptxgenjs 4.0.1 resolvable by Node (for example NODE_PATH="$(npm root -g)" after
 * `npm install -g pptxgenjs@4.0.1`) and LibreOffice for the PDF. Run from the repository root:
 * node scripts/build-deck.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
const require=createRequire(import.meta.url);
const pptxModule=require('pptxgenjs'),PptxGenJS=pptxModule.default||pptxModule;
const root=path.resolve('.'),out=path.join(root,'deliverables');
const C={ink:'183F35',gray:'52655E',paper:'F4F7F3',white:'FFFFFF',line:'93ABA0',green:'DBEEE4',blue:'E1ECF8',purple:'EAE5F5',amber:'F6EBCF',red:'F5E0E3',blueInk:'315D87',redInk:'9D3948',amberInk:'86601E',chart:'3B7A63',grid:'D9E2DD'};
// The canvas is 1280 x 720 px (13.333 x 7.5 in); sizes are written in px like the original layout.
const px=v=>v/96,pt=v=>Math.round(v*1.5)/2;
const pres=new PptxGenJS();
pres.layout='LAYOUT_WIDE';pres.author='achopikyan';pres.company='achopikyan';pres.title='Refund operations';

function text(s,value,x,y,w,h,size=22,color=C.gray,bold=false,options={}){
 s.addText(value,{x:px(x),y:px(y),w:px(w),h:px(h),fontFace:'Arial',fontSize:pt(size),color,bold,margin:0,valign:'top',isTextBox:true,...options});
}
function rect(s,x,y,w,h,fill=C.white,line=C.line){
 s.addShape(pres.shapes.RECTANGLE,{x:px(x),y:px(y),w:px(w),h:px(h),fill:{color:fill},line:{color:line,width:1}});
}
function node(s,title,detail,x,y,w,h,fill=C.white,titleSize=24,detailSize=20){
 rect(s,x,y,w,h,fill);text(s,title,x+16,y+13,w-32,titleSize*1.3,titleSize,C.ink,true);
 if(detail)text(s,detail,x+16,y+17+titleSize*1.35,w-32,h-titleSize*1.35-24,detailSize,C.gray);
}
function line(s,x1,y1,x2,y2,{dashed=false,head=true}={}){
 s.addShape(pres.shapes.LINE,{x:px(Math.min(x1,x2)),y:px(Math.min(y1,y2)),w:px(Math.abs(x2-x1)),h:px(Math.abs(y2-y1)),flipH:x2<x1,flipV:y2<y1,
  line:{color:C.line,width:1.8,dashType:dashed?'dash':'solid',endArrowType:head?'triangle':'none'}});
}
function path_(s,points,options={}){
 for(let i=1;i<points.length;i++)line(s,...points[i-1],...points[i],{...options,head:i===points.length-1&&options.head!==false});
}
function bullets(s,items,x,y,w,h,size=19,color=C.gray){
 text(s,items.map((value,i)=>({text:value,options:{bullet:{indent:16},breakLine:i<items.length-1}})),x,y,w,h,size,color,false,{paraSpaceAfter:pt(9)});
}
function stat(s,value,detail,x,y,w,h,fill,color=C.ink){
 rect(s,x,y,w,h,fill);text(s,value,x+18,y+16,w-36,48,36,color,true);text(s,detail,x+18,y+72,w-36,h-84,18,C.gray);
}
function slide(title,subtitle,notes){
 const s=pres.addSlide();s.background={color:C.paper};
 text(s,title,64,40,1152,58,40,C.ink,true);if(subtitle)text(s,subtitle,64,104,1152,36,22,C.gray);
 s.addNotes(notes);return s;
}
const label=(s,value,x,y,w=600)=>text(s,value,x,y,w,26,17,C.gray,true);
const footer=(s,value)=>text(s,value,64,654,1152,40,19,C.gray);

{
 const s=slide('Today: one queue, one forgotten rule','History sample: 248 unique requests from 1 June to 18 August 2026.',
  'Sources: data/history.csv deduplicated from 251 rows to 248 requests, and data/policy_notes.csv. The old auto rule decided 111 requests and four reviewers decided 137, recording 1,119 review minutes; never-arrived claims took 449.5 of them. Eight approved requests have a chargeback outcome note: RF-1005, RF-2042, RF-1045, RF-2083, RF-1027, RF-2111, RF-1065 (staff) and RF-2074 (old rule), $2,319 of refunds plus 8 x $25 fees; the refund amount stands in for the missing order amount. Seven staff approvals contradicted evidence already in the notes: signed proof of delivery, a customer confirming delivery or self-inflicted damage, sealed packaging, or an unconfirmed fraud flag on a new account. Four change-of-mind refunds were approved 18-27 days after delivery against a no-exception 14-day window; RF-1008, RF-2090 and RF-2143 were rejected and overturned on appeal. The old rule never reads notes: it approved damage claims of $51-53 without a photo (RF-2037, RF-2046, RF-2121), and on the pending queue it pays RF-1074 (already refunded in store) and RF-1075 (change of mind on day 22). Messy inputs: 3 exact duplicates, a conflicting RF-2183, amounts like "USD 120.00" or "$1,150.00", day-first and ISO-timestamp dates, fraud flags yes/Y/no/N/false/blank, inconsistent reason and category spelling, missing tenure, missing or negative delivery days.');
 label(s,'WHO IS INVOLVED',64,160);
 const flow=[['Customer','Web form or support desk',64,190,C.blue],['Support','Adds notes to requests',290,212,C.white],['Old auto rule','Unclear logic · decided 111',538,224,C.green],['4 reviewers','One mixed queue · decided 137',798,212,C.amber],['Fraud team','Checks flagged payments',1046,170,C.red]];
 for(const [title,detail,x,w,fill] of flow)node(s,title,detail,x,192,w,108,fill,23,18);
 for(let i=1;i<flow.length;i++)line(s,flow[i-1][2]+flow[i-1][3],246,flow[i][2],246);
 text(s,'The Refund Operations Manager owns the written policy, but nobody quite remembers the auto rule’s logic.',64,316,1152,30,19,C.ink);
 label(s,'WHERE TIME AND MONEY GO, AND WHERE IT BREAKS',64,374);
 stat(s,'1,119 min','of reviewer time on 137 requests; never-arrived claims took 450 of them',64,406,270,200,C.blue);
 stat(s,'$2,519','8 chargebacks with $25 fees; 7 were staff approvals against evidence already in the notes',358,406,270,200,C.red,C.redInk);
 stat(s,'7 decisions','inconsistent: 4 change-of-mind refunds after the 14-day limit, 3 rejections overturned on appeal',652,406,270,200,C.amber,C.amberInk);
 stat(s,'5 payouts','where the old rule ignored notes: 3 damage claims without a photo; today a double refund and a day-22 return',946,406,270,200,C.purple);
 footer(s,'Messy inputs too: duplicates, four amount formats, day-first dates, six fraud-flag spellings and reasons that contradict notes.');
}
{
 const s=slide('After: AI reads, code decides, people judge','Every request gets one explained route. The manager owns the rules and tests every change.',
  'Implementation: llm.py, domain.py, analysis_pipeline.py, storage.py, policy_management.py, experiments.py and shadow.py. The LLM extracts 21 predefined facts from allowlisted request-time fields and both notes, each with an exact quotation; outcomes, reviewer names, decisions and review minutes are excluded. The Python policy engine evaluates every enabled rule, resolves matches by priority, then applies policy-wide and execution checks. Auto Approve writes to a simulated SQLite ledger with idempotency and single-payment, daily, customer and release limits. Review opens the reviewer workspace; flagged payments go to Fraud Review until the fraud team confirms. A manager change is made in a draft version, replayed on the 248 historical requests, observed in Shadowtest on the same live requests without payments, and released explicitly; earlier versions keep a rollback preview.');
 node(s,'Request','CSV row and both notes',64,214,206,120,C.blue,23,19);
 node(s,'LLM extraction','21 facts with exact quotes',306,214,232,120,C.purple,23,19);
 node(s,'Policy engine',"Manager's rules + safety checks",574,214,232,120,C.green,23,19);
 line(s,270,274,306,274);line(s,538,274,574,274);
 const outcomes=[['Auto Approve','Simulated payment within limits',C.green,170],['Review','Reviewer workspace with evidence',C.amber,262],['Fraud Review','Fraud team confirms first',C.red,354]];
 path_(s,[[806,274],[828,274]],{head:false});line(s,828,207,828,391,{head:false});
 for(const [title,detail,fill,y] of outcomes){rect(s,852,y,364,74,fill);text(s,title,868,y+10,332,28,22,C.ink,true);text(s,detail,868,y+40,332,26,18,C.gray);line(s,828,y+37,852,y+37);}
 label(s,'THE MANAGER, WITHOUT AN ENGINEER',64,470);
 const steps=[['Draft rule','In words or with a form',64,250],['Backtest','248 historical requests',350,250],['Shadowtest','Live queue, no payments',636,250],['Release','Explicit, with rollback',922,294]];
 for(const [title,detail,x,w] of steps)node(s,title,detail,x,502,w,108,C.white,23,19);
 for(let i=1;i<steps.length;i++)line(s,steps[i-1][2]+steps[i-1][3],556,steps[i][2],556);
 path_(s,[[1069,502],[1069,448],[690,448],[690,334]],{dashed:true});
 footer(s,'Before: one queue and a rule nobody remembers. After: visible rules, explained outcomes, tested changes.');
}
{
 const s=slide('The line: what the system handles alone','Proposed policy v2. Anything that is not clearly simple goes to a person.',
  'Sources: backend/refundops/source_rebuild.py build_policies and broader_candidate, README.md and the saved Sol extraction in data/demo/refundops.sqlite3. v1 reconstructs the old rule from historical routing only: amount below $55, tenure at least 9 months, no prior refunds, clear fraud flag and the 14-day change-of-mind window; it agrees with 242 of 243 eligible decisions (RF-1002 is the exception). v2 has 10 ordinary rules plus policy-wide checks; photo-supported damage is capped at $150 and excludes customer-caused or no-product damage. v2 deliberately drops the inherited nine-month tenure cutoff; that is a hypothesis to compare by tenure cohort, not a proven boundary. Replay of the same 248 requests: v1 108 automatic proposals, $3,332.51, 1 human reference, 1 known chargeback on automatic; v2 108, $4,430, 32 references with $0 above the human amount, 0 known chargebacks; v3 125, $6,681.45, 44 references with $415 above the human amount in 3 cases. Compared with v1, v2 makes 31 requests automatic and returns 31 to Review. On the 20 pending requests v2 routes 2 to Auto Approve, 16 to Review and 2 to Fraud Review. 214 of 248 outcomes are blank; replay proposals are not payments, losses or calibrated rates.');
 rect(s,64,160,408,456,C.green);
 text(s,'Handled alone',86,178,364,30,24,C.ink,true);text(s,'Auto Approve',86,210,364,26,18,C.gray,true);
 bullets(s,['Wrong-size apparel up to $100','Change of mind up to $75, within 14 days','Apparel or home damage up to $50, or $150 with a photo','Our mistake, once confirmed: full refund','Stolen card, once the fraud team confirms: full refund'],86,250,364,280,19,C.ink);
 text(s,'Returns and damage also need no prior refunds, a clear fraud flag and notes that agree.',86,540,364,64,17,C.gray);
 rect(s,496,160,408,456,C.amber);
 text(s,'Goes to a person',518,178,364,30,24,C.ink,true);text(s,'Review or Fraud Review',518,210,364,26,18,C.gray,true);
 bullets(s,['Anything over $300','Repeat refunds in the last 12 months','Delivery proof or a carrier incident','Electronics, partial or customer-caused damage','Already refunded, a reason the notes contradict, or embedded instructions','A fraud flag without confirmation goes to the fraud team'],518,250,364,350,19,C.ink);
 label(s,'EVIDENCE · 248 REQUESTS',928,162,300);
 s.addChart(pres.charts.BAR,[{name:'Automatic proposals',labels:['v1','v2','v3'],values:[108,108,125]}],{x:px(928),y:px(190),w:px(288),h:px(196),barDir:'col',chartColors:[C.chart],
  showValue:true,dataLabelPosition:'outEnd',dataLabelColor:C.ink,dataLabelFontSize:12,dataLabelFontFace:'Arial',dataLabelFontBold:true,
  showTitle:true,title:'Automatic proposals',titleColor:C.ink,titleFontSize:12,titleFontFace:'Arial',showLegend:false,valAxisMaxVal:150,valAxisMinVal:0,valAxisMajorUnit:50,
  catAxisLabelColor:C.gray,catAxisLabelFontSize:12,catAxisLabelFontFace:'Arial',valAxisLabelColor:C.gray,valAxisLabelFontSize:10,valAxisLabelFontFace:'Arial',
  valGridLine:{color:C.grid,size:0.5},catGridLine:{style:'none'},catAxisLineShow:false,valAxisLineShow:false,barGapWidthPct:70});
 bullets(s,['v1 matches the old rule in 242 of 243 eligible decisions','v2: same count, different cases: 31 in, 31 out','v2: $0 above human amounts on 32 assessed, 0 known chargebacks','v3: $415 above human amounts in 3 cases'],928,398,288,220,16,C.ink);
 footer(s,'214 of 248 outcomes are unknown: the replay supports this line but does not prove it safe.');
}
{
 const s=slide('Reviewer: evidence to decision, in one place','What lands there: everything the policy does not take. Of the 20 pending requests, v2 sends 16 to Review and 2 to Fraud Review.',
  'Implementation: frontend/src/Workspace.tsx, ReviewDesk.tsx, components.tsx and backend/refundops/storage.py. Reviewer sections: Request details, Policy evaluation, Evidence, Chargeback risk, Customer history and collapsible Activity. Every enabled rule is shown with its conditions, the decisive rule and the quoted evidence. Request information and hold are Review workflow states, not extra routes. Every action needs an explanation and is recorded with an audit entry; optimistic versions, idempotency keys and database uniqueness prevent duplicate decisions or payments. Conflicting source rows such as RF-2183 must be reconciled before approval. Reviewer decisions become shared Shadowtest references; candidate predictions are never shown to reviewers. Chargeback estimates are scenario information, not calibrated probabilities.');
 node(s,'Request queue','All · Open · Waiting\nFraud · Completed',64,200,256,140,C.blue,24,19);
 rect(s,370,200,384,196,C.white);text(s,'Request workspace',388,214,348,30,24,C.ink,true);
 text(s,'Details + policy trace\nEvidence with quotes\nCustomer history\nChargeback risk + activity',388,254,348,130,19,C.gray);
 line(s,320,270,370,270);
 const actions=[['Approve','Full requested refund',C.green,184],['Partial refund','Reviewer sets the amount',C.amber,302],['Reject','Explain the decision',C.red,420]];
 line(s,754,298,786,298,{head:false});line(s,786,229,786,465,{head:false});
 for(const [title,detail,fill,y] of actions){node(s,title,detail,812,y,404,90,fill,24,19);line(s,786,y+45,812,y+45);}
 node(s,'Correct or verify','New input triggers fresh analysis',64,448,300,112,C.blue,23,18);
 node(s,'Wait or refer to fraud','Resume after new evidence',396,448,358,112,C.purple,23,18);
 path_(s,[[214,448],[214,420],[562,420],[562,396]],{dashed:true});
 rect(s,370,590,846,56,C.green);text(s,'Decision + audit → independent references for Shadowtest',390,606,806,28,22,C.ink,true);
}
{
 const s=slide('Manager: change the policy, see the effect first',"The brief's two changes, made in a draft version without an engineer.",
  'Implementation: rule_proposal.py, AddRuleDialog.tsx, PolicyRules.tsx, experiments.py and policy_management.py. Both changes are ordinary rules in v2, and a manager can add either to any draft with Describe with AI or Build manually. The AI drafting call returns exactly one complete rule; its schema has no question field, so ambiguous wording gets the most conservative reading, named in the rule, and the manager reviews the proposal before adding it. Rules are edited inline with autosave. "Anything over $300 comes to us": v2 rule Review amounts above $300, priority 950. Backtest on the 248 historical requests: 13 matches. Added to reconstructed v1 it changes no route, because the old rule never approved more than $55 automatically. "Stolen-card cases go straight through": policy note 5 refunds the real cardholder only after the fraud team confirms, so v2 has Confirmed stolen card: full refund, priority 880, and a flagged payment without confirmation always goes to Fraud Review (domain.py). A reported-fraud rule matches all 11 historical stolen-card reports, but the required check sends every one to Fraud Review; confirmation arrives after the decision, so the confirmed-only rule has no historical matches. Priority decides between the two rules: a confirmed stolen-card refund above $300 still comes to Review. Tested and Shadowtest versions are locked; release needs the configured prospective checks and an explicit manager action.');
 const examples=[[64,'“From now on, anything over $300 comes to us.”','Amount above $300 → Review · priority 950','Backtest on 248 historical requests: 13 matches. Added to v1 it changes no route: the old rule never auto-approved more than $55.'],
  [652,'“From now on, stolen-card cases go straight through.”','Fraud confirmed → Auto Approve · priority 880','Backtest: a rule on reported fraud matches all 11 stolen-card reports, but each still goes to the fraud team first. Confirmation comes later.']];
 for(const [x,quote,rule,result] of examples){
  rect(s,x,160,564,252,C.white);
  text(s,quote,x+22,180,520,64,23,C.ink,true);
  rect(s,x+22,256,520,48,C.green);text(s,rule,x+38,268,488,26,19,C.ink,true);
  text(s,result,x+22,320,520,80,19,C.gray);
 }
 text(s,'Both rules are in v2. AI drafts always return a rule, with vague wording read the safe way. Priority decides between rules: a confirmed stolen card above $300 still comes to Review.',64,428,1152,56,18,C.ink);
 const steps=[['Draft','Edit inline or describe',64,250,C.blue],['Backtest','248 historical requests',350,250,C.purple],['Shadowtest','Live queue, no payments',636,250,C.amber],['Release','Checks pass · rollback ready',922,294,C.green]];
 for(const [title,detail,x,w,fill] of steps)node(s,title,detail,x,512,w,96,fill,22,18);
 for(let i=1;i<steps.length;i++)line(s,steps[i-1][2]+steps[i-1][3],560,steps[i][2],560);
}
{
 const s=slide('AI reads meaning. Code controls money.','The model answers predefined questions with quotes. It never approves, sets an amount or pays.',
  'Sources: llm.py, domain.py, analysis_pipeline.py, rule_proposal.py, README.md and data/demo/refundops.sqlite3 table demo_llm_calls. Model choice: constrained multilingual extraction requires comparing notes with structured fields; gpt-6.1-sol passed the 20-case development acceptance suite, where an earlier gpt-5.4-mini run passed 14/20 with different prompts, so this is not a controlled comparison. Measured OpenRouter run: 268 successful calls, mean provider-reported cost $0.0047, total $1.25, median latency 7.3 s, 248/248 historical analyses complete and 20/20 pending acceptance cases. Native OpenAI run: 20 successful calls, all 21 questions assessed with schema, source and quote validation, v2 routing matched 20/20 (2 Auto Approve, 16 Review, 2 Fraud Review), median latency 5.3 s, 40,557 tokens; OpenAI reports no dollar cost. These are development cases, not unseen accuracy. Requests are allowlisted and identifiers redacted; outcome notes, reviewers, decisions and review minutes never reach the model. Notes are data, never instructions: embedded instructions are flagged and the request goes to Review. Deliberately not AI: routes, amounts, payments, limits, rule discovery and metrics.');
 const flow=[['Source input','Allowed fields + both notes; outcomes excluded',64,250,C.blue],['LLM extraction','21 predefined facts with exact quotes',350,250,C.purple],['Validation','Schema + quotes; unknown stays unknown',636,250,C.blue],['Rules + checks','Python decides route, amount and payment',922,294,C.green]];
 for(const [title,detail,x,w,fill] of flow)node(s,title,detail,x,164,w,150,fill,23,19);
 for(let i=1;i<flow.length;i++)line(s,flow[i-1][2]+flow[i-1][3],239,flow[i][2],239);
 label(s,'MODEL, COST AND EVALUATION',64,346);
 stat(s,'gpt-6.1-sol','via OpenAI (default) or OpenRouter; chosen for multilingual notes read against structured fields',64,378,270,200,C.white);
 stat(s,'≈ $0.005','per request: 268 calls, $1.25 in total (OpenRouter-reported); median 5–7 s',358,378,270,200,C.white);
 stat(s,'20 / 20','pending acceptance cases; v2 routing matched 20/20 through OpenAI; gpt-5.4-mini passed 14/20',652,378,270,200,C.white);
 stat(s,'248 / 248','historical extractions complete and validated against quotes',946,378,270,200,C.white);
 footer(s,'Not AI: routes, amounts, payments, limits, rule discovery and metrics. AI also drafts rules that the manager reviews.');
}
{
 const s=slide('How we would know the line is wrong','Before switching on: Backtest and Shadowtest. After: the same few numbers every week.',
  'Implementation: financial.py, decision_metrics.py, policy_management.py, shadow.py and CurrentPerformance.tsx. Backtest reports rates, proposed dollars, differences from historical decisions, known adverse outcomes, manual-work opportunity and explicit cost assumptions. Shadowtest adds prospective sample size, shared human references, amount errors, unknown assessments, confidence bounds and conditional projected loss; confidence calculations assume representative independent customer groups. Saved release defaults from financial.py: at least 24 Shadowtest hours, 30 prospective automatic proposals and 30 reviewed customer groups, five changed cases, zero critical violations, a one-sided 95% upper overpayment error bound at most 10%, and projected stress at most $1,000 over the next 100 automatic approvals. Atomic single-payment, daily, customer/day, release-dollar and operation-count limits are always enforced. The targets on this slide are proposals for the manager, who owns the tolerances. The 44% automatic share is v2 replay (108 of 248); today 8 of 248 historical requests ended in a chargeback and 3 rejections were overturned on appeal. Rollback restores an earlier version while preserving recorded decisions, payments and spent limits. Production alerting and incident response are future work.');
 label(s,'THE FEW NUMBERS',64,160);label(s,'GOOD LOOKS LIKE',444,160);
 const rows=[['Automatic share and review minutes','About 44% automatic, as in v2 replay, with reviewer time moving to cases that need judgment'],
  ['Overpayment on audited automatic refunds','$0 above the human amount; release check: 95% upper error at most 10%'],
  ['Chargebacks on automatic refunds','Zero, each one investigated; today 8 of 248 requests ended in one'],
  ['Reviewer overrides and appeals','Falling; today 3 rejections were overturned on appeal']];
 rows.forEach(([metric,good],i)=>{const y=192+i*100;rect(s,64,y,360,86,C.blue);text(s,metric,82,y+14,324,60,20,C.ink,true);rect(s,436,y,384,86,C.white);text(s,good,454,y+12,348,66,18,C.gray);});
 rect(s,856,160,360,386,C.red);
 text(s,'Roll back when',878,178,316,30,24,C.redInk,true);
 bullets(s,['Any critical violation: a double payment or a limit exceeded','A chargeback or confirmed overpayment on an automatic refund above tolerance','Error bound above 10% or stress above $1,000 per 100 approvals','Automatic share jumps or drops, for example during a carrier incident'],878,222,316,300,18,C.ink);
 text(s,'Rollback keeps payments and spent limits recorded.',878,496,316,44,16,C.gray);
 footer(s,'Default release gate: 24 h of Shadowtest, 30 automatic proposals, 30 reviewed customers, 0 critical violations.');
}
{
 const s=slide('Deferred, and what to build next','Deferred from this version; next once there is more independent data.',
  'Deferred, as requested or by scope: authentication, cloud deployment, real payment, messaging, carrier and fraud integrations, an independently labelled unseen evaluation, a calibrated chargeback model, a distributed worker queue and production security and operations. Next: collect mature independently reviewed outcomes; reserve later time periods and disjoint customers; train and calibrate a chargeback and loss model with uncertainty and drift monitoring; extend discovery to richer AND/OR interactions, then evaluate support, errors and financial exposure out of time and prune conflicting or overlapping candidates. Candidate rules stay explainable and need manager approval. Run instructions and API-key setup are in README.md; Windows and macOS launches were verified. UI roles are not authenticated identities. All money effects are simulated. AI coding assistance and one rejected implementation are disclosed in README.');
 rect(s,64,170,1152,130,C.blue);text(s,'Better evidence for learning',88,190,1104,32,26,C.ink,true);
 text(s,'Collect mature outcomes and independent reviewer labels.\nReserve future time windows and unseen customers for evaluation.',88,234,1104,60,21,C.gray);
 path_(s,[[640,300],[640,330]],{head:false});line(s,334,330,946,330,{head:false});line(s,334,330,334,370);line(s,946,330,946,370);
 node(s,'Calibrated risk model','Estimate chargeback probability and dollar loss.\nShow uncertainty, calibration and drift.\nKeep the manager’s risk tolerances explicit.',64,370,540,160,C.green,25,20);
 node(s,'More powerful rule discovery','Search richer AND / OR interactions and segments.\nValidate future-period support, errors and loss.\nPrune overlapping or conflicting candidates.',676,370,540,160,C.purple,25,20);
 footer(s,'Proposals stay explainable. Managers inspect the evidence and choose which rules to release.');
}

fs.mkdirSync(out,{recursive:true});
const pptx=path.join(out,'write-up.pptx');
await pres.writeFile({fileName:pptx});
execFileSync(process.env.SOFFICE||'soffice',['--headless','--convert-to','pdf','--outdir',out,pptx],{stdio:'inherit'});
console.log('Eight-slide write-up written to deliverables/write-up.pptx and write-up.pdf.');
