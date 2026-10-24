import os,random,threading,time,unittest
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import QPointF,QTimer
from PySide6.QtWidgets import QApplication
from chart_curve import SmoothTrace
from codex_navigation import CodexNavigation
from test_live_compaction import SID,OTHER
APP=QApplication.instance() or QApplication([])

class CurveTests(unittest.TestCase):
    def test_original_samples_are_exact_and_extrema_are_not_exceeded(self):
        generator=random.Random(7)
        for values in ([0,0,100,0,0,50,0],[10]*24,[0]*24,[100,0,0,0],*[ [generator.randrange(100) for _ in range(24)] for _ in range(50)]):
            trace=SmoothTrace([QPointF(i*7,value) for i,value in enumerate(values)])
            self.assertEqual(trace.path.elementCount(),1+3*(len(values)-1))
            for i,value in enumerate(values):self.assertAlmostEqual(trace.head(i/(len(values)-1)).y(),value,places=8)
            for i,(a,b) in enumerate(zip(values,values[1:])):
                for step in range(21):
                    y=trace.head((i+step/20)/(len(values)-1)).y()
                    self.assertGreaterEqual(y,min(a,b)-1e-8);self.assertLessEqual(y,max(a,b)+1e-8)
    def test_rendered_bezier_and_reveal_head_follow_identical_geometry(self):
        trace=SmoothTrace([QPointF(i*10,value) for i,value in enumerate([20,70,30,40,0])])
        for i in range(4):
            a,b=trace.points[i:i+2];c1=trace.path.elementAt(1+i*3);c2=trace.path.elementAt(2+i*3)
            for step in range(11):
                t=step/10;rendered=(1-t)**3*a.y()+3*(1-t)**2*t*c1.y+3*(1-t)*t*t*c2.y+t**3*b.y()
                self.assertAlmostEqual(rendered,trace.head((i+t)/4).y(),places=8)
        for i in range(1,4):
            left=trace.path.elementAt(i*3-1);right=trace.path.elementAt(i*3+1);point=trace.points[i]
            self.assertAlmostEqual((point.y()-left.y)/(point.x()-left.x),(right.y-point.y())/(right.x-point.x()))
    def test_peak_tangent_is_horizontal_and_flat_zero_stays_zero(self):
        trace=SmoothTrace([QPointF(i,y) for i,y in enumerate([0,0,4,0,0])])
        self.assertEqual(trace.slopes[2],0);self.assertEqual(trace.head(.1).y(),0)
    def test_single_empty_two_points_and_nonuniform_axis(self):
        self.assertIsNone(SmoothTrace([]).head(.5))
        self.assertEqual(SmoothTrace([QPointF(2,3)]).head(.4),QPointF(2,3))
        self.assertEqual(SmoothTrace([QPointF(0,0),QPointF(4,8)]).head(.5),QPointF(2,4))
        trace=SmoothTrace([QPointF(0,0),QPointF(2,3),QPointF(10,4)])
        self.assertEqual(trace.head(.2),QPointF(2,3))

class NavigationTests(unittest.TestCase):
    def wait(self,condition):
        end=time.monotonic()+10
        while not condition():
            APP.processEvents();time.sleep(.003)
            self.assertLess(time.monotonic(),end,'navigation did not settle')
    def test_blocked_system_dispatch_does_not_block_ui_and_only_latest_click_is_queued(self):
        gate=threading.Event();started=threading.Event();returned=threading.Event();called=[];ticks=[];threads=[]
        def open_(session):
            called.append(session);threads.append(threading.get_ident());started.set();gate.wait(10);returned.set()
        nav=CodexNavigation(open_)
        try:
            self.assertTrue(nav.open(SID));self.assertTrue(started.wait(5))
            self.assertNotEqual(threads[0],threading.get_ident())
            self.assertFalse(returned.is_set());self.assertTrue(nav.busy)
            nav.open(SID);nav.open(OTHER);nav.open('33333333-3333-4333-8333-333333333333');nav.open(OTHER)
            QTimer.singleShot(0,lambda:ticks.append(not returned.is_set()));APP.processEvents();self.assertEqual(ticks,[True]);self.assertEqual(called,[SID])
            gate.set();self.wait(lambda:not nav.busy)
            self.assertEqual(called,[SID,OTHER])
            with patch('codex_navigation.time.monotonic',return_value=nav.last_request+.1):self.assertFalse(nav.open(OTHER))
            self.assertEqual(len(called),2)
        finally:gate.set();nav.close();nav.deleteLater();APP.processEvents()
    def test_invalid_id_and_failure_never_open_an_unrelated_thread_or_clear_read_state(self):
        calls=[];nav=CodexNavigation(lambda sid:calls.append(sid))
        try:
            for value in ('bad','../escape',SID+'?run=1'):
                with self.assertRaises(OSError):nav.open(value)
            self.assertEqual(calls,[])
        finally:nav.close();nav.deleteLater();APP.processEvents()
        errors=[]
        def fail(sid):raise OSError('unable to dispatch')
        nav=CodexNavigation(fail);nav.error.connect(errors.append)
        try:nav.open(SID);self.wait(lambda:bool(errors));self.assertEqual(errors,['unable to dispatch'])
        finally:nav.close();nav.deleteLater();APP.processEvents()
    def test_shutdown_discards_pending_request(self):
        gate=threading.Event();called=[]
        def slow(sid):called.append(sid);gate.wait(2)
        nav=CodexNavigation(slow)
        try:
            nav.open(SID);self.wait(lambda:bool(called));nav.open(OTHER);nav.close();gate.set();self.wait(lambda:not nav.busy)
            self.assertEqual(called,[SID])
        finally:gate.set();nav.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main()
