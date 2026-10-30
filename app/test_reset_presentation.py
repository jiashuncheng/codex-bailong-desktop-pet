import unittest
from datetime import datetime
from unittest.mock import patch
from PySide6.QtCore import QTimeZone
from reset_presentation import reset_view

NOW=1803100000
def snapshot(seconds,**extra):
    return {'pending':dict(id='preview',scheduled=NOW+seconds,reset_type='regular',text='预计分批落实，以实际到账为准。',**extra)}

class ResetPresentationTests(unittest.TestCase):
    def test_hours_and_minutes_replace_decimal_hours(self):
        view=reset_view(snapshot(12.41*3600),now=NOW)
        self.assertEqual(view['eyebrow'],'预计还有')
        self.assertEqual(view['parts'],[('12','小时'),('25','分钟')])
        self.assertIn('12 小时 25 分钟',view['description'])
        self.assertTrue(view['note'].startswith('最晚 '))
        self.assertIn('北京时间',view['description'])
        self.assertIn('不代表账户额度已到账',view['description'])
    def test_minute_and_deadline_boundaries(self):
        for seconds,value,unit,phase in [(3600,'1','小时','scheduled'),(3599,'1','小时','scheduled'),(3540,'59','分钟','scheduled'),(61,'2','分钟','scheduled'),(60,'1','分钟','scheduled'),(59,'<1','分钟','scheduled'),(0,'待确认','','pending'),(-3600,'待确认','','pending')]:
            with self.subTest(seconds=seconds):
                v=reset_view(snapshot(seconds),now=NOW)
                self.assertEqual((v['value'],v['unit'],v['phase']),(value,unit,phase))
    def test_countdown_tick_reaches_next_display_change(self):
        for seconds in [12.45*3600,100.5*3600,185,60,45]:
            v=reset_view(snapshot(seconds),now=NOW)
            next_view=reset_view(snapshot(seconds),now=NOW+v['next_change']+.001)
            self.assertGreater(v['next_change'],0)
            self.assertNotEqual((v['parts'],v['phase']),(next_view['parts'],next_view['phase']))
    def test_minute_carry_zero_padding_and_long_countdowns(self):
        for seconds,parts in [(45000,[('12','小时'),('30','分钟')]),(3636,[('1','小时'),('01','分钟')]),(3601,[('1','小时'),('01','分钟')]),(3600,[('1','小时'),('00','分钟')]),(3541,[('1','小时'),('00','分钟')]),(3540,[('59','分钟')]),(100*3600+5*60,[('100','小时'),('05','分钟')])]:
            self.assertEqual(reset_view(snapshot(seconds),now=NOW)['parts'],parts)
    def test_confirmation_requires_source_to_clear_pending(self):
        self.assertEqual(reset_view(snapshot(-100),now=NOW)['phase'],'pending')
        self.assertEqual(reset_view({'pending':None,'scheduled':None},now=NOW)['phase'],'empty')
    def test_unknown_and_failure_are_not_zero_countdowns(self):
        for data,error,phase in [(None,False,'loading'),(None,True,'unavailable'),({'pending':{'id':'undated'}},False,'undated')]:
            v=reset_view(data,error,NOW);self.assertEqual(v['phase'],phase);self.assertEqual(v['unit'],'');self.assertIsNone(v['next_change'])
            self.assertNotEqual(v['value'],'0')
        v=reset_view(snapshot(7200),True,NOW)
        self.assertEqual(v['value'],'2');self.assertIn('上次',v['eyebrow']);self.assertIn('更新失败',v['description'])
    def test_banked_notice_keeps_its_identity_and_original_copy(self):
        data=snapshot(7200);data['pending']['reset_type']='banked'
        v=reset_view(data,now=NOW)
        self.assertEqual(v['title'],'备用重置');self.assertIn(data['pending']['text'],v['description'])
    def test_empty_feed_shows_pacific_clock_in_summer_and_winter(self):
        for utc,date,abbreviation in [('2026-10-29T19:30:00+00:00','10/29','UTC-07:00'),('2026-12-01T20:30:00+00:00','12/01','UTC-08:00')]:
            with self.subTest(utc=utc):
                v=reset_view({'pending':None},now=datetime.fromisoformat(utc).timestamp())
                self.assertEqual(v['phase'],'empty');self.assertEqual(v['eyebrow'],'美西现在')
                self.assertEqual(v['parts'],[('12:30','')]);self.assertTrue(v['pacific_clock'])
                self.assertEqual(v['note'],'美西 '+date)
                self.assertIn(abbreviation,v['description']);self.assertIn('不是额度重置时间',v['description'])
    def test_pacific_date_rolls_over_without_a_feed_refresh(self):
        midnight=datetime.fromisoformat('2026-10-30T07:00:00+00:00').timestamp()
        before=reset_view({},now=midnight-20)
        self.assertEqual(before['parts'],[('23:59','')]);self.assertEqual(before['note'],'美西 10/29')
        self.assertEqual(before['next_change'],20)
        after=reset_view({},now=midnight)
        self.assertEqual(after['parts'],[('00:00','')]);self.assertEqual(after['note'],'美西 10/30')
    def test_clock_handles_both_daylight_saving_transitions(self):
        for utc,value in [('2026-03-08T09:59:00+00:00','01:59'),('2026-03-08T10:00:00+00:00','03:00'),
                          ('2026-11-01T08:59:00+00:00','01:59'),('2026-11-01T09:00:00+00:00','01:00')]:
            v=reset_view({},now=datetime.fromisoformat(utc).timestamp())
            self.assertEqual(v['parts'],[(value,'')])
    def test_empty_clock_tick_follows_next_minute_without_feed_refresh(self):
        now=datetime.fromisoformat('2026-10-29T19:30:47+00:00').timestamp()+.25
        view=reset_view({},now=now);self.assertEqual(view['value'],'12:30')
        self.assertAlmostEqual(view['next_change'],12.75)
        self.assertEqual(reset_view({},now=now+view['next_change'])['value'],'12:31')
    def test_empty_feed_warning_stays_visible_beside_clock(self):
        for error in [True,dict(code='network',message='公告连接失败'),dict(code='cache_write')]:
            v=reset_view({},error,now=NOW)
            self.assertEqual(v['eyebrow'],'美西现在');self.assertIsNotNone(v['next_change'])
            self.assertIn('未缓存' if isinstance(error,dict) and error.get('code')=='cache_write' else '查询失败',v['note'])
    def test_calendar_never_replaces_a_real_pending_or_undated_announcement(self):
        for seconds in [7200,-1]:
            v=reset_view(snapshot(seconds),now=NOW)
            self.assertNotIn('美西',v['eyebrow']);self.assertFalse(v['pacific_clock'])
        self.assertEqual(reset_view({'pending':dict(id='later')},now=NOW)['value'],'时间待定')
    def test_missing_zone_data_keeps_empty_feed_instead_of_guessing_an_offset(self):
        with patch('reset_presentation.PACIFIC',QTimeZone()):
            v=reset_view({},now=NOW)
        self.assertEqual(v['value'],'暂无安排');self.assertIsNone(v['next_change'])

if __name__=='__main__':unittest.main()
