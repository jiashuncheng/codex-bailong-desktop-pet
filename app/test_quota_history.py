import io
import json
import sqlite3
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

from quota_history import WEEK,migrate,store,record_line,partition,summarize_cycles,snapshot,import_step,anomaly,visible_anomaly


class QuotaHistoryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');migrate(self.db)
        self.db.execute('''CREATE TABLE usage (stamp REAL,tokens INTEGER,model TEXT,
            input_tokens INTEGER,output_tokens INTEGER,known INTEGER)''')
        self.db.execute('CREATE INDEX usage_stamp ON usage(stamp)')
        self.start=1800000000
    def tearDown(self):self.db.close()
    def token(self,stamp,n,model='model-a'):
        self.db.execute('INSERT INTO usage VALUES(?,?,?,?,?,1)',(stamp,n,model,int(n*.8),int(n*.2)))
    def cycle(self,start,amount=1200,model='model-a'):
        for offset,remaining in [(100,100),(86400,70),(172800,40)]:
            store(self.db,start+offset,start+WEEK,remaining,plan='pro')
        self.token(start+200,amount//2,model);self.token(start+100000,amount//2,model)
    def test_history_estimate_and_comparison_survive_reopening_view(self):
        self.cycle(self.start);self.cycle(self.start+WEEK,600)
        rows=summarize_cycles(self.db,self.start+WEEK+172900)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['used'],600)
        self.assertEqual(rows[0]['estimated_total'],1000)
        self.assertEqual(rows[1]['estimated_total'],2000)
        self.assertEqual(rows[0]['per_percent'],10)
        self.assertEqual(rows[0]['change'],-50)
        self.assertEqual(rows,summarize_cycles(self.db,self.start+WEEK+172900))
    def test_estimate_starts_at_five_observed_percentage_points_not_total_spent(self):
        s=self.start
        store(self.db,s+1,s+WEEK,60,plan='pro');store(self.db,s+100,s+WEEK,56,plan='pro')
        self.token(s+50,1000)
        self.assertIsNone(summarize_cycles(self.db,s+101)[0]['estimated_total'])
        store(self.db,s+200,s+WEEK,55,plan='pro')
        row=summarize_cycles(self.db,s+201)[0]
        self.assertEqual(row['estimated_total'],20000);self.assertFalse(row['eligible'])
    def test_model_change_and_extra_reset_are_not_direct_peers(self):
        self.cycle(self.start);self.cycle(self.start+WEEK,600,'model-b')
        rows=summarize_cycles(self.db,self.start+WEEK+172900)
        self.assertIsNone(rows[0]['change'])
        self.assertIn('模型',rows[0]['comparison_reason'])
    def test_sustained_refill_splits_but_single_delayed_read_does_not(self):
        deadline=self.start+WEEK
        def sample(t,r):return (self.start+t,deadline,r,'log','',None,'')
        rows=partition([sample(1,80),sample(2,30),sample(3,90),sample(4,29)])
        self.assertEqual(len(rows),1)
        rows=partition([sample(1,80),sample(2,30),sample(3,90),sample(4,89)])
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1]['kind'],'extra')
        self.assertEqual(rows[1]['start'],self.start+3)
        self.assertEqual(rows[1]['samples'][0][2],90)
    def test_isolated_small_rise_replays_without_poisoning_saved_cycle(self):
        s=self.start;deadline=s+WEEK
        for offset,remaining,source in [(1,80,'log'),(100,60,'live'),
                (105,62,'log'),(108,60,'log'),(120,55,'live')]:
            store(self.db,s+offset,deadline,remaining,source,plan='pro')
        self.token(s+50,1000);self.token(s+110,500)
        row=summarize_cycles(self.db,s+121)[0]
        self.assertFalse(row['corrected']);self.assertFalse(row['rise_pending'])
        self.assertEqual(row['estimated_total'],6000);self.assertTrue(row['eligible'])
        self.assertEqual(row['sample_count'],4)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM quota_observations').fetchone()[0],5)
        self.assertEqual(summarize_cycles(self.db,s+121)[0],row)
    def test_unconfirmed_rise_pauses_estimate_then_recovers_after_lower_read(self):
        s=self.start;deadline=s+WEEK
        for offset,remaining in [(1,80),(100,60),(105,62)]:
            store(self.db,s+offset,deadline,remaining,plan='pro')
        self.token(s+50,1000)
        row=summarize_cycles(self.db,s+106)[0]
        self.assertTrue(row['rise_pending']);self.assertFalse(row['corrected'])
        self.assertIsNone(row['estimated_total']);self.assertFalse(row['eligible'])
        self.assertIn('待确认',row['comparison_reason'])
        store(self.db,s+108,deadline,60,plan='pro')
        row=summarize_cycles(self.db,s+109)[0]
        self.assertFalse(row['rise_pending']);self.assertFalse(row['corrected'])
        self.assertEqual(row['estimated_total'],5000)
    def test_confirmed_small_rise_still_blocks_a_misleading_estimate(self):
        s=self.start;deadline=s+WEEK
        for offset,remaining in [(1,80),(100,60),(105,64),(110,63)]:
            store(self.db,s+offset,deadline,remaining,plan='pro')
        self.token(s+50,1000)
        rows=summarize_cycles(self.db,s+111)
        self.assertEqual(len(rows),1);self.assertTrue(rows[0]['corrected'])
        self.assertFalse(rows[0]['rise_pending']);self.assertIsNone(rows[0]['estimated_total'])
    def test_duplicate_timestamp_cannot_confirm_a_rise(self):
        s=self.start;deadline=s+WEEK
        rows=partition([(s+1,deadline,60,'live','pro',None,''),
            (s+2,deadline,62,'log','',None,''),
            (s+2,deadline+120,62,'log','',None,''),
            (s+3,deadline,60,'live','pro',None,'')])
        self.assertEqual(len(rows),1);self.assertFalse(rows[0].get('corrected',False))
        self.assertNotIn('rise_candidate',rows[0])
    def test_older_window_does_not_consume_a_pending_refill(self):
        s=self.start;deadline=s+WEEK
        rows=partition([(s+1,deadline,30,'log','',None,''),
            (s+2,deadline,90,'log','',None,''),
            (s+3,deadline-3600,90,'log','',None,''),
            (s+4,deadline,89,'log','',None,'')])
        self.assertEqual(len(rows),2);self.assertEqual(rows[1]['kind'],'extra')
        self.assertEqual(rows[1]['start'],s+2)
    def test_reset_deadline_jitter_does_not_split_one_cycle(self):
        rows=partition([(self.start+100,self.start+WEEK,90,'log','',None,''),
            (self.start+200,self.start+WEEK+120,85,'log','',None,''),
            (self.start+300,self.start+WEEK+260,80,'log','',None,''),
            (self.start+400,self.start+WEEK,75,'live','',None,'')])
        self.assertEqual(len(rows),1);self.assertEqual(len(rows[0]['samples']),4)
    def test_missing_baseline_uses_observed_delta_not_full_cycle_division(self):
        start=self.start;deadline=start+WEEK
        self.token(start+10,5000) # Before the first quota sample; excluded from slope.
        for offset,r in [(100,60),(200,45),(300,30)]:store(self.db,start+offset,deadline,r)
        self.token(start+150,1000);self.token(start+250,500)
        result=summarize_cycles(self.db,start+301)[0]
        self.assertEqual(result['used'],6500)
        self.assertEqual(result['estimated_total'],5000)
        self.assertEqual(result['drop'],30)
    def test_partial_import_never_creates_confident_estimates_and_cache_survives(self):
        self.cycle(self.start);now=self.start+WEEK+1
        first=snapshot(self.db,None,now,True,dict(pending=False,errors=0))
        self.assertEqual(first['cycles'][0]['estimated_total'],2000)
        restricted=snapshot(self.db,None,now,False,dict(pending=False,errors=1))
        self.assertEqual(restricted['cycles'][0]['estimated_total'],2000)
        self.assertTrue(restricted['cycles'][0]['cached'])
    def test_log_samples_include_zero_token_events_and_are_deduplicated(self):
        stamp=self.start+100
        data=dict(timestamp=datetime.fromtimestamp(stamp,timezone.utc).isoformat(),type='event_msg',
            payload=dict(type='token_count',info=None,rate_limits=dict(limit_id='codex',
                primary=dict(used_percent=25,window_minutes=10080,resets_at=self.start+WEEK))))
        raw=json.dumps(data).encode()+b'\n'
        record_line(self.db,raw);record_line(self.db,raw)
        self.assertEqual(self.db.execute('SELECT remaining FROM quota_observations').fetchall(),[(75,)])
        data['payload']['rate_limits']['limit_id']='other'
        record_line(self.db,json.dumps(data).encode())
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM quota_observations').fetchone()[0],1)
    def test_import_resumes_without_touching_existing_token_offsets(self):
        raw=b'{"type":"session_meta","payload":{}}\n'
        path=Path('quota-history-synthetic.jsonl')
        with patch.object(Path,'stat',return_value=type('Stat',(),{'st_size':len(raw)})()), \
             patch.object(Path,'open',side_effect=lambda *a,**k:io.BytesIO(raw)):
            first=import_step(self.db,[path],max_bytes=1)
            second=import_step(self.db,[path],max_bytes=1)
        self.assertEqual(first['bytes_read'],len(raw))
        self.assertEqual(second['bytes_read'],0)
        self.assertFalse(second['pending'])
    def test_anomaly_requires_same_known_plan_stable_model_and_coverage(self):
        import copy
        self.cycle(self.start);self.cycle(self.start+WEEK,600)
        self.db.execute("UPDATE quota_observations SET plan='pro'")
        now=self.start+WEEK+172900
        rows=summarize_cycles(self.db,now);alert=anomaly(rows,now)
        self.assertEqual(alert['change'],-50)
        for field,value in [('plan','plus'),('plan',''),('model','model-b'),
                ('model_share',.72),('eligible',False),('complete',False),('corrected',True),('kind','extra')]:
            other=copy.deepcopy(rows);other[0][field]=value
            self.assertIsNone(anomaly(other,now),(field,value))
        self.assertIsNone(anomaly(rows,now+1000))
        data=dict(quota_history=dict(anomaly=alert))
        windows=[dict(name='一周',plan='pro',resetsAt=rows[0]['reset_at'])]
        self.assertEqual(visible_anomaly(data,windows,now),alert)
        self.assertIsNone(visible_anomaly(dict(data,partial=True),windows,now))
        windows[0]['plan']='plus';self.assertIsNone(visible_anomaly(data,windows,now))
    def test_plan_upgrade_splits_cycles_and_conflicting_live_plan_is_retained(self):
        s=self.start
        store(self.db,s+1,s+WEEK,90,plan='PRO')
        store(self.db,s+2,s+WEEK,80,plan='pro')
        store(self.db,s+3,s+WEEK,70,plan='plus')
        rows=summarize_cycles(self.db,s+4)
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['kind'],'changed')
        store(self.db,s+3,s+WEEK,70,'live',plan='plus')
        self.assertEqual(self.db.execute('SELECT plan FROM quota_observations ORDER BY stamp DESC LIMIT 1').fetchone()[0],'plus')
    def test_recent_api_plan_survives_missing_log_plan_but_not_a_plan_change(self):
        from quota_history import inherit_live_plan
        from enhanced_core import windows_from_limits
        w=dict(name='一周',remaining=50,resetsAt=self.start+WEEK)
        live=([dict(w,plan='pro')],self.start)
        self.assertEqual(inherit_live_plan([w],live,self.start+30)[0]['plan'],'pro')
        self.assertNotIn('plan',inherit_live_plan([w],live,self.start+181)[0])
        self.assertEqual(inherit_live_plan([dict(w,plan='plus')],live,self.start+30)[0]['plan'],'plus')
        parsed=windows_from_limits(dict(plan_type='plus',primary=dict(used_percent=50,window_minutes=10080,resets_at=self.start+WEEK)))
        self.assertEqual(parsed[0]['plan'],'plus')


if __name__=='__main__':unittest.main()
