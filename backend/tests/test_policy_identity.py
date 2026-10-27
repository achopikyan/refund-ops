from fastapi.testclient import TestClient
from refundops.domain import initial_policy
from refundops.main import create_app


def test_policy_drafts_need_no_name_and_get_distinct_stable_versions(tmp_path):
    app=create_app(tmp_path/'versions.sqlite3',seed=False,auto_analyze=False)
    store=app.state.store
    original=store.policy()
    data=initial_policy()
    data.pop('name')
    with TestClient(app,headers={'X-Demo-Role':'manager'}) as client:
        first=client.post('/api/policies/drafts',json=data)
        second=client.post('/api/policies/drafts',json=data)
        assert first.status_code==second.status_code==200
        one,two=first.json(),second.json()
        assert one['version']==original['version']+1
        assert two['version']==one['version']+1 and one['id']!=two['id']
        assert one['data']['name']==two['data']['name']=='Policy version'
        listed=client.get('/api/policies').json()
        assert next(p for p in listed if p['id']==one['id'])['version']==one['version']
    assert store.policy()==original
