"""Balanced random rounds and click integration without real desktop data."""
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import json
import unittest

from action_shuffle import ActionShuffle


def action(key):
    return dict(id=key,file=key+'.webp')


class ActionShuffleTests(unittest.TestCase):
    def test_every_round_covers_all_23_and_prefix_counts_differ_by_at_most_one(self):
        items=[action(str(i)) for i in range(23)]
        for seed in range(10):
            import random
            rng=random.Random(seed)
            with patch('action_shuffle.random.shuffle',side_effect=rng.shuffle),patch('action_shuffle.random.randrange',side_effect=rng.randrange):
                bag=ActionShuffle();seen=[];counts=Counter({item['id']:0 for item in items})
                for _ in range(23*12):
                    key=bag.next(items)['id'];seen.append(key);counts[key]+=1
                    self.assertLessEqual(max(counts.values())-min(counts.values()),1)
                for start in range(0,len(seen),23):self.assertEqual(len(set(seen[start:start+23])),23)
                self.assertTrue(all(a!=b for a,b in zip(seen,seen[1:])))

    def test_forced_boundary_repeat_is_replaced(self):
        bag=ActionShuffle();items=[action('a'),action('b')]
        def shuffle(queue):
            if bag.last is not None:
                queue.remove(bag.last);queue.append(bag.last)
        with patch('action_shuffle.random.shuffle',side_effect=shuffle),patch('action_shuffle.random.randrange',return_value=0) as swap:
            self.assertEqual([bag.next(items)['id'] for _ in range(6)],['b','a','b','a','b','a'])
            self.assertEqual(swap.call_count,2)

    def test_reordered_or_reloaded_items_keep_progress_and_use_current_objects(self):
        items=[action('a'),action('b'),action('c')];bag=ActionShuffle()
        with patch('action_shuffle.random.shuffle'):
            self.assertEqual(bag.next(items)['id'],'c')
            refreshed=[dict(item,quality='hd') for item in reversed(items)]
            selected=bag.next(refreshed)
            self.assertEqual(selected['id'],'b');self.assertEqual(selected['quality'],'hd')
            self.assertEqual(bag.next(refreshed)['id'],'a')

    def test_changed_pool_cannot_return_stale_action_and_empty_singleton_are_safe(self):
        bag=ActionShuffle();bag.next([action('old'),action('other')])
        self.assertIsNone(bag.next([]))
        self.assertEqual([bag.next([action('new')])['id'] for _ in range(3)],['new']*3)
        self.assertEqual({bag.next([action('a'),action('b')])['id'] for _ in range(2)},{'a','b'})

    def test_duplicate_playback_files_get_one_slot(self):
        bag=ActionShuffle();a=action('a');b=dict(a,id='alias')
        self.assertEqual({bag.next([a,b,action('c')])['file'] for _ in range(2)},{'a.webp','c.webp'})


class ClickIntegrationTests(unittest.TestCase):
    def pet(self,manifest):
        return SimpleNamespace(manifest=manifest,idles=[],choose=Mock(),click_actions=ActionShuffle(),
                               gate=SimpleNamespace(state='idle'),_visibility_ready=True,
                               _desktop_hidden=False,settings=dict(character_visible=True))

    def test_builtin_clicks_cover_23_and_do_not_change_drag_or_landing(self):
        from desktop import DesktopPet
        from desktop_services import all_items
        manifest=json.loads((Path(__file__).resolve().parents[1]/'outputs/白龙桌宠素材/素材清单.json').read_text(encoding='utf-8'))
        pet=self.pet(manifest);before=json.dumps(manifest,sort_keys=True)
        for _ in range(46):DesktopPet.single_click(pet)
        ids=[call.args[0]['id'] for call in pet.choose.call_args_list]
        expected={item['id'] for item in all_items(manifest)}-{'drag','landing'}
        self.assertEqual(len(expected),23)
        self.assertEqual(set(ids[:23]),expected);self.assertEqual(set(ids[23:]),expected)
        self.assertNotEqual(ids[22],ids[23])
        self.assertEqual(json.dumps(manifest,sort_keys=True),before)
        self.assertTrue(all(call.kwargs==dict(interactive=True) for call in pet.choose.call_args_list))

    def test_ignored_clicks_do_not_consume_round(self):
        from desktop import DesktopPet
        pet=self.pet(dict(idle=action('a'),variants=[action('b')]))
        DesktopPet.single_click(pet);remaining=list(pet.click_actions.remaining)
        pet.gate.state='task';DesktopPet.single_click(pet)
        pet.gate.state='idle';pet._desktop_hidden=True;DesktopPet.single_click(pet)
        pet._desktop_hidden=False;pet.settings['character_visible']=False;DesktopPet.single_click(pet)
        self.assertEqual(pet.choose.call_count,1);self.assertEqual(pet.click_actions.remaining,remaining)


if __name__=='__main__':unittest.main()
