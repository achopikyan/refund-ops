"""Synthetic builders for isolated regression tests; never imported into the application workspace."""
from copy import deepcopy
import csv
import io
from refundops.domain import COLUMNS,validate_policy


def candidates(v2):
    careful=deepcopy(v2)
    # A general category/uncertainty choice, never an exception for a historical ID.
    careful['rules']=[r for r in careful['rules'] if r['id']!='electronics-damage-review']
    careful['rules'].append({'id':'electronics-damage-review','name':'Review electronics damage after merchant-error checks',
        'priority':700,'conditions':[{'field':'category','op':'eq','value':'electronics'},
                                   {'field':'stated_reason','op':'eq','value':'arrived_damaged'}],
        'match':'all','action':'review','enabled':True,'reason_code':'damage_origin','reason':''})
    broad=deepcopy(careful);broad['name']='Policy v3'
    broad['rules']=[r for r in broad['rules'] if r['id'] not in ('repeat-requests','carrier-incident','electronics-damage-review','broad-returns')]
    broad['rules'].append({'id':'broad-returns','name':'Apparel returns up to $300, including repeat requests','priority':650,
        'conditions':[{'field':'category','op':'eq','value':'apparel'},
                      {'field':'stated_reason','op':'in','value':['wrong_size','changed_mind']},
                      {'field':'amount_cents','op':'lte','value':30000},
                      {'field':'fraud_flag','op':'eq','value':False}],
        'match':'all','action':'auto_approve','enabled':True,'reason_code':'simple_return','reason':''})
    for p in (careful,broad):
        _,issues=validate_policy(p)
        if issues:raise ValueError(issues)
    return careful,broad


def fixture():
    """Separate input and post-review reference files. No labels enter model inputs."""
    requests=[];references=[]
    scenarios=[('BASE',10,40,24,0,'approved',40),('EXPAND',40,65,6,0,'approved',65),
               ('REPEAT',10,45,24,2,'rejected',0),('AMOUNT',10,150,24,0,'partial',37.5)]
    for tag,count,amount,tenure,prior,action,allowed in scenarios:
        for index in range(1,count+1):
            rid=f'DEMO-{tag}-{index:03d}'
            row=dict.fromkeys(COLUMNS,'')
            row.update(request_id=rid,customer_id=f'DEMO-C-{tag}-{index:03d}',requested_at='2026-10-27',
                amount_usd=str(amount),tenure_months=str(tenure),prior_refunds_12m=str(prior),days_since_delivery='5',
                fraud_flag='no',stated_reason='wrong_size',category='apparel',payment_method='card',decision='pending',
                customer_note='The size does not fit. I would like to return the shirt.',
                support_note='Correct size was shipped. Customer requests a return.')
            requests.append(row)
            references.append({'request_id':rid,'action':action,'amount_cents':round(allowed*100),
                'reason':f'Synthetic scenario reference for {tag}. Authored independently of candidate predictions; not a production finding.'})
    return requests,references


def csv_content(rows):
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=COLUMNS);writer.writeheader();writer.writerows(rows)
    return stream.getvalue()
