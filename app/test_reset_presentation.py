import unittest
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
        for data,error,phase in [(None,False,'loading'),(None,True,'unavailable'),({},False,'empty'),({'pending':{'id':'undated'}},False,'undated')]:
            v=reset_view(data,error,NOW);self.assertEqual(v['phase'],phase);self.assertEqual(v['unit'],'');self.assertIsNone(v['next_change'])
            self.assertNotEqual(v['value'],'0')
        v=reset_view(snapshot(7200),True,NOW)
        self.assertEqual(v['value'],'2');self.assertIn('上次',v['eyebrow']);self.assertIn('更新失败',v['description'])
    def test_banked_notice_keeps_its_identity_and_original_copy(self):
        data=snapshot(7200);data['pending']['reset_type']='banked'
        v=reset_view(data,now=NOW)
        self.assertEqual(v['title'],'备用重置');self.assertIn(data['pending']['text'],v['description'])

if __name__=='__main__':unittest.main()
