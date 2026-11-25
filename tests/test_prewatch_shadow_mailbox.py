"""Offline shadow transport gates; never count as a real Phase A."""
from copy import deepcopy
from datetime import timedelta
import json
import pytest

from collector import prewatch_shadow_mailbox as s
from collector.prewatch_ready import encoded, digest
from collector.prewatch_ledger_reader import SCOPE
from tests.test_prewatch_ready import NOW, DAY


def packet():
    return {"schema":"prewatch_ready_v1","status":"SOURCE_READY","diagnostic_status":"LIVE_LEDGER_SOURCE_DIAGNOSTIC",
            "reference_utc":NOW.isoformat(),"date_oslo":DAY,"replay_only":False,"phase_a_completed":False,
            "bet_authority":False,"operational_publication_allowed":False,"freeze_recheck_required":True,
            "ledger_exclusion":"CALLER_SUPPLIED_VERIFIED_IDS",
            "ledger_evidence":{"evidence_kind":"GOOGLE_API_READ","scope":SCOPE,"read_finished_utc":NOW.isoformat()},
            "selected":{"metadata":{"ledger_race_id":DAY+"|Solvalla|1","latest_freeze_utc":(NOW+timedelta(minutes=10)).isoformat(),
                                    "scheduled_start_iso":(NOW+timedelta(minutes=20)).isoformat()}},
            "queue":[{"ledger_race_id":DAY+"|Solvalla|1"}],"min_analysis_window_seconds":120}


def env(mode="shadow_preflight", approval=""):
    return {"GITHUB_ACTIONS":"true","GITHUB_REPOSITORY_ID":str(s.releases.REPO_ID),"GITHUB_REF":"refs/heads/main",
            "GITHUB_WORKFLOW_REF":s.WORKFLOW,"GITHUB_EVENT_NAME":"workflow_dispatch","GITHUB_JOB":"shadow",
            "SHADOW_MODE":mode,"SHADOW_APPROVAL":approval,"SHADOW_CONSUMER_GUARD_VERIFIED":"true","COLLECTOR_RUN_ID":"123","GITHUB_RUN_ID":"456",
            "PREWATCH_LEDGER_ACCESS_TOKEN":"synthetic"}


def test_shadow_top_level_never_authorizes_operation():
    p = packet()
    e = s.envelope(p,"123")
    assert e["status"] == "SHADOW_ONLY" and "selected" not in e
    assert not e["bet_authority"] and not e["operational_publication_allowed"] and not e["phase_a_completed"]
    assert s.decode_body(encoded(e).decode()) == e
    e["packet"]["queue"] = []
    with pytest.raises(ValueError):
        s.decode_body(encoded(e).decode())


@pytest.mark.parametrize("key,value",[("bet_authority",True),("phase_a_completed",True),
    ("operational_publication_allowed",True),("replay_only",True),("status","NO_ELIGIBLE_RACE")])
def test_unsafe_packet_rejected(key,value):
    p=packet();p[key]=value
    with pytest.raises(ValueError):
        s.envelope(p,"123")


def test_patch_never_runs_without_approval(monkeypatch):
    def forbidden(*a,**kw):
        pytest.fail("network reached")
    monkeypatch.setattr(s.urllib.request,"build_opener",forbidden)
    body=encoded(s.envelope(packet(),"123")).decode()
    for e in [env(),env("shadow_consume"),env("shadow_publish"),dict(env("shadow_publish",s.APPROVAL),GITHUB_REF="refs/heads/dev")]:
        with pytest.raises(ValueError):
            s.patch_body(body,e)


def test_mailbox_identity_and_marker():
    r={"id":s.releases.MARKER_ID,"tag_name":s.releases.MARKER_TAG,"draft":True,"published_at":None,"assets":[],
       "body":json.dumps({"schema":"prewatch_ready_v1","status":"NOT_INITIALIZED","bet_authority":False})}
    assert s.mailbox(lambda path:r)[1] is None
    with pytest.raises(ValueError,match="SHADOW_MAILBOX_IDENTITY_INVALID"):
        s.mailbox(lambda path:dict(r,draft=False))
    with pytest.raises(ValueError,match="SHADOW_MAILBOX_IDENTITY_INVALID"):
        s.mailbox(lambda path:dict(r,assets=[{}]))


def test_idempotence_older_and_same_clock_conflicts():
    v=s.envelope(packet(),"123")
    assert s.plan_body(({},None),v)[1]
    assert not s.plan_body(({},v),v)[1]
    p=packet();p["reference_utc"]=(NOW-timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError,match="SHADOW_OLDER_WRITE_REJECTED"):
        s.plan_body(({},v),s.envelope(p,"123"))
    with pytest.raises(ValueError,match="SHADOW_SAME_CLOCK_CONFLICT"):
        s.plan_body(({},v),s.envelope(packet(),"124"))


def test_positive_ledger_exclusion_and_stale():
    p=packet()
    result={"evidence_kind":"GOOGLE_API_READ","scope":SCOPE,"read_finished_utc":NOW.isoformat(),"completed_ids":[]}
    assert s.final_ledger(p,reader=lambda day:result,clock=lambda:NOW)==result
    with pytest.raises(ValueError,match="SHADOW_ALREADY_COMPLETED"):
        s.final_ledger(p,reader=lambda day:dict(result,completed_ids=[p["selected"]["metadata"]["ledger_race_id"]]),clock=lambda:NOW)
    with pytest.raises(ValueError,match="SHADOW_LEDGER_STALE"):
        s.final_ledger(p,reader=lambda day:result,clock=lambda:NOW+timedelta(seconds=31))


def test_final_clock_gate():
    p=packet(); l={"read_finished_utc":NOW.isoformat()}
    assert s.final_gate(p,NOW,NOW,l,clock=lambda:NOW)==NOW
    with pytest.raises(ValueError,match="SHADOW_FINAL_RECHECK_EXPIRED"):
        s.final_gate(p,NOW,NOW,l,clock=lambda:NOW+timedelta(seconds=31))
    p["ledger_evidence"]["read_finished_utc"] = (NOW+timedelta(minutes=9)).isoformat()
    with pytest.raises(ValueError,match="DIAGNOSTIC_PACKET_EXPIRED"):
        s.final_gate(p,NOW,NOW,l,clock=lambda:NOW+timedelta(minutes=9))


def test_missing_official_field_and_driver_response():
    assert s.race_payload({"success":True,"result":{"1":[{"startNumber":1}]}},"starts",1)==[{"startNumber":1}]
    with pytest.raises(ValueError,match="SHADOW_OFFICIAL_RACE_MISSING"):
        s.race_payload({"success":True,"result":{}},"starts",1)
    with pytest.raises(ValueError,match="SHADOW_DRIVER_CHANGES_INVALID"):
        s.race_payload({"success":True,"result":{}},"driver_changes",1)


def test_newer_archive_fail_closed():
    from tests.test_prewatch_ready import DAY,RUN,ARCH,TAG
    idx={"date_oslo":DAY,"run_id":RUN,"meeting_feeds":[{"release_tag":TAG}]}
    marker={"id":s.releases.MARKER_ID,"tag_name":s.releases.MARKER_TAG,"draft":True}
    original={"id":1,"tag_name":ARCH,"draft":True}
    newer={"id":2,"tag_name":ARCH+"-newer","draft":True}
    assert s.current_archive(idx,getter=lambda path:[marker,original],clock=lambda:NOW)==NOW
    with pytest.raises(ValueError,match="SHADOW_NEWER_ARCHIVE_AVAILABLE"):
        s.current_archive(idx,getter=lambda path:[marker,original,newer],clock=lambda:NOW)


def test_patch_exact_id_body_only_and_guard(monkeypatch):
    e=env("shadow_publish",s.APPROVAL)
    e["GH_TOKEN"]="synthetic"
    body=encoded(s.envelope(packet(),"123")).decode()
    with pytest.raises(ValueError,match="SHADOW_APPROVAL_REQUIRED"):
        s.patch_body(body,dict(e,SHADOW_CONSUMER_GUARD_VERIFIED="false"))
    class Response:
        status=200
        def __enter__(self): return self
        def __exit__(self,*args): return False
    class Opener:
        def open(self,req,timeout):
            assert req.full_url == "https://api.github.com/repos/"+s.releases.REPO+"/releases/458013574"
            assert req.get_method()=="PATCH"
            assert json.loads(req.data)=={"body":body}
            return Response()
    monkeypatch.setattr(s.urllib.request,"build_opener",lambda *a:Opener())
    s.patch_body(body,e)


def test_consumer_full_field_reconstruction(tmp_path,monkeypatch):
    from tests.test_prewatch_ready_integration import source_fixture
    from collector.prewatch_ready_integration import prepare, verify_sources
    from collector.prewatch_ledger_reader import SCOPE
    from pathlib import Path
    feed,archive,notes,records=source_fixture(tmp_path)
    monkeypatch.setattr("collector.prewatch_ready_integration.utcnow",lambda:NOW)
    monkeypatch.setattr("collector.prewatch_ledger_reader.read_live",lambda day:{
        "evidence_kind":"GOOGLE_API_READ","scope":SCOPE,"read_finished_utc":NOW.isoformat(),"completed_ids":[]})
    p=prepare(feed,archive,notes,records,NOW,read_ledger=True)
    idx=json.loads((feed/"index.json").read_bytes())
    ids=verify_sources(feed,archive,notes,records,NOW)
    v=s.envelope(p,"123")
    assert s.validate_consumed(v,feed,idx,ids,NOW)==p
    p["selected"]["source_pack"]["program"]["entrants"]=[]
    with pytest.raises(ValueError,match="SHADOW_FULL_FIELD_MISMATCH"):
        s.validate_consumed(s.envelope(p,"123"),feed,idx,ids,NOW)


def test_roster_recheck_rejects_changed_official_payload(tmp_path):
    from zipfile import ZipFile
    from tests.test_prewatch_ready import MID, RUN
    p=packet()
    p["collector_run_id"]=RUN
    start={"success":True,"result":{"1":[{"startNumber":1,"isScratched":False}]}}
    changes={"success":True,"result":[]}
    prefix=f"{DAY}/{RUN}/meetings/{MID}/"
    archive=tmp_path/"original.zip"
    roster={}
    with ZipFile(archive,"w") as z:
        for key,name,path,raw in (("starts_source","starts",f"/api/racedays/{MID}/starts",start),
                                  ("driver_changes_source","driver_changes",f"/api/game/program/{MID}/driverChanges",changes)):
            data=encoded(raw);z.writestr(prefix+name+".raw.json",data)
            roster[key]={"url":"https://www.rikstoto.no"+path,"sha256":digest(data)}
    p["selected"]["source_pack"]={"program":{"race":{"meeting_id":MID,"race_number":1}},"official_roster":roster}
    assert s.recheck_roster(p,archive,getter=lambda u:start if u.endswith("/starts") else changes,clock=lambda:NOW)==NOW
    changed=deepcopy(start);changed["result"]["1"][0]["isScratched"]=True
    with pytest.raises(ValueError,match="SHADOW_ROSTER_CHANGED_REFRESH_REQUIRED"):
        s.recheck_roster(p,archive,getter=lambda u:changed if u.endswith("/starts") else changes,clock=lambda:NOW)
