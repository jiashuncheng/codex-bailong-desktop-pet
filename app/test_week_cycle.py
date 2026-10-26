"""Focused tests for reset boundaries and the quota-based estimate."""
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from reset_watch import LocalResetEvidence
from week_cycle import WEEK,context,summarize,usage


class WeekCycleTests(unittest.TestCase):
    def test_natural_boundary_and_observed_extra_reset(self):
        observed=1_800_000_000;deadline=observed+100_000
        windows=[dict(name='一周',remaining=70,resetsAt=deadline)]
        natural=context(windows,{},observed,'live')
        self.assertEqual(natural['start'],deadline-WEEK)
        self.assertEqual(natural['start_source'],'inferred')
        extra=observed-20_000
        detected=context(windows,{'reset':dict(window='一周',observed=extra)},observed,'live')
        self.assertEqual(detected['start'],extra)
        self.assertEqual(detected['start_source'],'detected')
        self.assertIsNone(context(windows,{},observed,'session'))
        self.assertIsNone(context([dict(name='5小时',remaining=70,resetsAt=deadline)],{},observed,'live'))

    def test_announced_partial_refill_is_recorded(self):
        observed=1_800_000_000;deadline=observed+100_000
        evidence=LocalResetEvidence.__new__(LocalResetEvidence)
        evidence.path=Path('unused-local-reset-evidence.json')
        evidence.state={'window':dict(name='一周',remaining=40,reset=deadline,observed=observed-600)}
        announcement={'pending':dict(id='extra',reset_type='bonus',announced=observed-300,scheduled=observed+600)}
        with patch('desktop_core.atomic_json'):
            evidence.observe([dict(name='一周',remaining=55,resetsAt=deadline)],observed,'live',announcement)
        self.assertEqual(evidence.state['reset']['observed'],observed)

    def test_indexed_range_excludes_previous_and_future_usage(self):
        db=sqlite3.connect(':memory:')
        try:
            db.execute('CREATE TABLE usage (stamp REAL,tokens INTEGER)')
            db.execute('CREATE INDEX usage_stamp ON usage(stamp)')
            db.executemany('INSERT INTO usage VALUES (?,?)',[(99,800),(100,20),(150,30),(201,400)])
            self.assertEqual(usage(db,dict(start=100,through=200)),(50,2))
            plan=' '.join(str(row[-1]) for row in db.execute(
                'EXPLAIN QUERY PLAN SELECT COALESCE(SUM(tokens),0),COUNT(*) '
                'FROM usage WHERE stamp>=? AND stamp<=?',(100,200)))
            self.assertIn('usage_stamp',plan)
        finally:db.close()

    def test_estimate_only_when_data_supports_it(self):
        cycle=dict(start=100,through=200,reset_at=300,start_source='detected',remaining=75)
        self.assertEqual(summarize(cycle,500,2,True,now=201)['estimated_total'],2000)
        self.assertIsNone(summarize(cycle,500,2,False,now=201)['estimated_total'])
        self.assertIsNone(summarize(cycle,500,2,True,now=1200)['estimated_total'])
        self.assertIsNone(summarize(dict(cycle,remaining=98),500,2,True,now=201)['estimated_total'])
        self.assertIsNone(summarize(cycle,0,0,True,now=201)['estimated_total'])


if __name__=='__main__':unittest.main()
