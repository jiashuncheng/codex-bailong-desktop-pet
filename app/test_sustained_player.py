import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from PySide6.QtWidgets import QApplication
from stream_player import StreamPlayer,PreparedSegment
from sustained_player import SustainedPlayback
from sustained_assets import profile_paths,seam_items
from status_reactions import Reaction

APP=QApplication.instance() or QApplication([])

def drain(player):
    result=[]
    while True:
        raw,delay,index=player.frames.get(timeout=4)
        if raw is None:
            assert index is None,index
            player.ended=True;return result
        result.append((raw,delay,index))

class SegmentTests(unittest.TestCase):
    def setUp(self):
        # Hosted Windows TEMP may contain RUNNER~1; profiles use resolved paths.
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.source=self.root/'source.webp';self.seam=self.root/'seam.webp'
        frames=[Image.new('RGBA',(16,16),(20*i,40,80,255)) for i in range(10)]
        frames[0].save(self.source,save_all=True,append_images=frames[1:],duration=42,lossless=True)
        frames[6].save(self.seam,save_all=True,append_images=[frames[5]],duration=42,lossless=True)
        self.p=StreamPlayer();self.s=SustainedPlayback()
        self.item=dict(id='work02',file='source.webp',sustained=dict(start=3,end=6,sourceFrames=10,seamFile='seam.webp',seamFrames=2))
        self.profile=profile_paths(self.root,self.item);self.owner=Reaction('working','work02','a','1')
    def tearDown(self):self.s.cancel();self.p.close();self.assertTrue(__import__('decode_runtime').STATS.drain());self.tmp.cleanup()
    def test_inclusive_range_cache_pixels_indexes_and_resize_cursor(self):
        first=self.p.start(self.source,16,start_frame=3,end_frame=6,cache_loop=True);cold=drain(self.p)
        self.assertEqual([i for _,_,i in cold],[4,5,6]);self.assertEqual(first.toImage().pixelColor(0,0).red(),60)
        with patch('stream_player.Image.open',side_effect=AssertionError('decoded again')):
            warmfirst=self.p.start(self.source,16,start_frame=3,end_frame=6,cache_loop=True);warm=drain(self.p)
        self.assertEqual(cold,warm);self.assertEqual(first.toImage(),warmfirst.toImage())
        self.p.start(self.source,16,start_frame=5,end_frame=6)
        self.p.playhead=.021;image=self.p.resize(32);self.assertEqual(image.width(),32)
        self.assertEqual(self.p.frame_index,5);self.assertEqual(self.p.range_end,6)
        self.assertAlmostEqual(self.p.next_time,.021,places=3);self.assertEqual([i for _,_,i in drain(self.p)],[6])
    def test_invalid_ranges_and_profile_cannot_escape_or_omit_tail(self):
        for a,b in ((5,4),(-1,3),(2,10),(10,None)):
            with self.subTest(a=a,b=b),self.assertRaises(ValueError):self.p.start(self.source,16,start_frame=a,end_frame=b)
        for changes in (dict(end=9),dict(seamFile='../outside.webp'),dict(start=True),dict(seamFrames=25)):
            item=dict(self.item,sustained=dict(self.item['sustained'],**changes))
            with self.assertRaises(ValueError):profile_paths(self.root,item)
    def test_entrance_once_repeated_body_then_original_tail(self):
        self.s.begin(self.p,self.profile,self.owner,16);self.assertEqual(self.s.phase,'enter')
        self.assertEqual([i for _,_,i in drain(self.p)],list(range(1,7)))
        for cycle in range(8):
            _,done=self.s.boundary(self.p,16);self.assertFalse(done);self.assertEqual(self.s.phase,'seam');drain(self.p)
            _,done=self.s.boundary(self.p,16);self.assertFalse(done);self.assertEqual(self.s.phase,'body')
            self.assertEqual(self.p.frame_index,3);self.assertEqual([i for _,_,i in drain(self.p)],[4,5,6])
        self.assertTrue(self.s.tail.ready.wait(4))
        self.s.request(False);self.s.boundary(self.p,16);self.assertEqual(self.s.phase,'exit');self.assertEqual(self.p.frame_index,7)
        self.assertEqual([i for _,_,i in drain(self.p)],[8,9]);self.assertTrue(self.s.boundary(self.p,16)[1]);self.assertFalse(self.s.active)
        self.assertGreater(self.p.loop_cache.stats()['hits'],8);self.assertLessEqual(self.p.loop_cache.stats()['bytes'],self.p.loop_cache.limit)
    def test_exit_requested_during_seam_returns_to_body_before_tail(self):
        self.s.begin(self.p,self.profile,self.owner,16);drain(self.p);self.s.boundary(self.p,16)
        self.s.request(False);drain(self.p);self.s.boundary(self.p,16)
        self.assertEqual(self.s.phase,'body');drain(self.p)
        self.assertTrue(self.s.tail.ready.wait(4))
        self.s.boundary(self.p,16);self.assertEqual(self.s.phase,'exit')
    def test_cancel_stops_worker_without_retaining_owner(self):
        self.s.begin(self.p,self.profile,self.owner,32);self.s.cancel()
        self.assertFalse(self.s.active);self.assertIsNone(self.s.owner);self.assertIsNone(self.s.warmer)
    def test_seam_resources_do_not_create_extra_logical_actions(self):
        from desktop_services import all_items
        m=dict(idle=dict(id='idle',file='idle.webp'),workAnimations=[self.item]);self.assertEqual(len(all_items(m)),2)
        self.assertEqual(seam_items(m)[0]['playbackFile'],'seam.webp')
    def test_prepared_tail_adopts_without_gui_image_open_and_preserves_all_frames(self):
        tail=PreparedSegment(self.source,16,7,9)
        self.assertTrue(tail.ready.wait(3))
        with patch('stream_player.Image.open',side_effect=AssertionError('GUI seek')):
            image=self.p.adopt(tail);values=drain(self.p)
        self.assertEqual(image.toImage().pixelColor(0,0).red(),140)
        self.assertEqual([i for _,_,i in values],[8,9]);self.assertEqual(self.p.range_end,9)
    def test_unready_tail_waits_at_a_repaired_loop_boundary(self):
        self.s.begin(self.p,self.profile,self.owner,16);drain(self.p)
        self.s.tail.ready.wait(3);self.s.tail.ready.clear();self.s.request(False)
        self.s.boundary(self.p,16);self.assertEqual(self.s.phase,'seam')
        self.s.tail.ready.set();drain(self.p);self.s.boundary(self.p,16);drain(self.p)
        self.s.boundary(self.p,16);self.assertEqual(self.s.phase,'exit')
    def test_variants_choose_only_prepared_ranges_without_repeating_and_keep_original_tail(self):
        self.item['sustained']['variants']=[dict(start=i,end=6,seamFile='seam.webp',seamFrames=2) for i in (3,2,1)]
        profile=profile_paths(self.root,self.item);self.s.rng.seed(17);self.s.begin(self.p,profile,self.owner,16);drain(self.p)
        self.assertTrue(self.s.warm_ready.wait(4));seen=[]
        body_keys=[k for k in self.p.loop_cache.entries if k[0]==str(self.source)]
        self.assertEqual(len(body_keys),1);self.assertEqual(body_keys[0][-2:],(1,6))
        for _ in range(12):
            with patch('stream_player.Image.open',side_effect=AssertionError('GUI seek')):self.s.boundary(self.p,16)
            seen.append(self.s.variant_index);drain(self.p)
            with patch('stream_player.Image.open',side_effect=AssertionError('GUI seek')):self.s.boundary(self.p,16)
            start=self.s.variant['start'];self.assertEqual(self.p.frame_index,start);self.assertEqual([i for _,_,i in drain(self.p)],list(range(start+1,7)))
            self.assertEqual(self.s.speed_factor(self.p),1.)
            self.p.playhead=(7-start)/48;self.assertAlmostEqual(self.s.speed_factor(self.p),self.s.cycle_speed)
        self.assertEqual(set(seen),{0,1,2});self.assertTrue(all(a!=b for a,b in zip(seen,seen[1:])));self.assertLessEqual(self.p.loop_cache.stats()['bytes'],self.p.loop_cache.limit)
        self.assertTrue(self.s.tail.ready.wait(4))
        self.s.request(False);self.s.boundary(self.p,16);self.assertEqual(self.s.phase,'exit');self.assertEqual(self.p.frame_index,7);drain(self.p)
    def test_unprepared_variant_is_not_selected_and_range_must_share_tail(self):
        self.item['sustained']['variants']=[dict(start=2,end=5,seamFile='seam.webp',seamFrames=2)]
        with self.assertRaises(ValueError):profile_paths(self.root,self.item)
        self.s.profile=dict(self.profile,variants=[dict(self.profile,start=2)]);self.s.variant=self.profile;self.s.variant_index=0
        self.s.choose_cycle(self.p,16);self.assertEqual(self.s.variant['start'],3)
    def test_full_loop_eviction_keeps_prepared_first_frames_off_gui_seek_path(self):
        import threading
        self.s.begin(self.p,self.profile,self.owner,16);drain(self.p);self.assertTrue(self.s.warm_ready.wait(4))
        self.assertEqual(len(self.s.seeds),2)
        with self.p.loop_cache.lock:self.p.loop_cache.entries.clear();self.p.loop_cache.bytes=0
        original=Image.open
        def background_only(*args,**kwargs):
            if threading.current_thread() is threading.main_thread():raise AssertionError('GUI seek after eviction')
            return original(*args,**kwargs)
        with patch('stream_player.Image.open',side_effect=background_only):
            self.s.boundary(self.p,16);drain(self.p);self.s.boundary(self.p,16)
            self.assertEqual(self.p.frame_index,3);self.assertEqual([i for _,_,i in drain(self.p)],[4,5,6])
    def test_shared_body_can_use_two_thirds_of_budget_without_evicting_all_seams(self):
        from loop_cache import DecodedLoopCache
        cache=DecodedLoopCache(limit=120);cache.put('idle',[],45);cache.put('seam-one',[],15);cache.put('seam-two',[],15)
        self.assertTrue(cache.begin('union',reserve=80));self.assertLessEqual(cache.stats()['bytes'],40)
        cache.put('union',[],76,entry_limit=80)
        self.assertIsNotNone(cache.get('union'));self.assertLessEqual(cache.stats()['bytes'],120)
        self.assertIsNotNone(cache.get('seam-one'));self.assertIsNotNone(cache.get('seam-two'))
        cache.put('oversize',[],121,entry_limit=200);self.assertIsNone(cache.get('oversize'))
    def test_body_and_original_tail_share_one_source_open_with_exact_pixels(self):
        calls=[];original=Image.open
        def counted(path,*a,**kw):
            calls.append(Path(path));return original(path,*a,**kw)
        self.s.profile=self.profile;self.s.phase='enter'
        with patch('sustained_player.Image.open',side_effect=counted):
            self.s.prewarm(self.p,16)
            self.assertTrue(self.s.tail.ready.wait(4));self.assertTrue(self.s.warm_ready.is_set())
            first=self.p.adopt(self.s.tail);frames=drain(self.p)
            self.assertEqual(first.toImage().pixelColor(0,0).red(),140)
            self.assertEqual([(raw[0],i) for raw,_,i in frames],[(160,8),(180,9)])
        self.assertEqual(calls.count(self.source),1)
        self.assertEqual(calls.count(self.seam),1)
        self.assertLessEqual(self.p.frames.qsize(),6)

if __name__=='__main__':unittest.main()
