# SPDX-License-Identifier: GPL-3.0-only
"""UI adapter smoke tests using doubles, NOT Pythonista/iPhone execution."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import mindustry_pythonista as m
from pythonista_stub import scene,ui,touch


class PythonistaAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.data=Path(self.tmp.name)
        self.patcher=patch('mindustry_pythonista.data_directory',return_value=self.data)
        self.patcher.start()
        self.cls=m.make_scene_class(scene,ui)
        self.s=self.cls()
        self.s.setup()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def world_point(self,x,y):
        cx,cy=self.s.view_center()
        return (cx+(x-self.s.camera_x)*m.TILE*self.s.zoom,
                cy+(y-self.s.camera_y)*m.TILE*self.s.zoom)

    def test_setup_help_overlay_and_300_frames(self):
        self.assertEqual(self.s.overlay_kind,'help')
        self.assertEqual(len(self.s.buttons),16)  # Dedicated six-button rotation row.
        self.s.close_overlay()
        for _ in range(300):self.s.update()
        self.assertFalse(self.s._failed)
        self.assertEqual(self.s.world.tick_count,600)
        self.assertGreater(self.s.world.stats['delivered'],0)

    def test_help_overlay_pauses_simulation(self):
        self.s.update()
        self.s.update()
        self.assertEqual(self.s.world.tick_count,0)

    def test_portrait_landscape_layout_bounds(self):
        for width,height in ((320,568),(390,844),(844,390),(1024,768)):
            with self.subTest(width=width,height=height):
                self.s.size=SimpleNamespace(w=width,h=height)
                self.s.did_change_size()
                self.assertGreater(height-self.s.header_height-self.s.bar_top,50)
                for button in self.s.buttons+self.s.overlay_buttons:
                    x,y,w,h=button['rect']
                    self.assertGreaterEqual(x,0)
                    self.assertGreaterEqual(y,0)
                    self.assertLessEqual(x+w,width+1e-6)
                    self.assertLessEqual(y+h,height+1e-6)

    def test_build_by_tap_consumes_copper(self):
        s=self.s
        s.close_overlay()
        s.perform('conveyor')
        p=self.world_point(17.5,10.5)
        self.assertTrue(s.is_world_point(p))
        before=s.world.stock['copper']
        s.touch_began(touch(1,p))
        self.assertIsNone(s.world.at(17,10))
        s.touch_ended(touch(1,p))
        self.assertEqual(s.world.at(17,10).kind,'conveyor')
        self.assertEqual(s.world.stock['copper'],before-1)

    def test_pinch_never_builds_a_tile(self):
        s=self.s
        s.close_overlay()
        s.perform('conveyor')
        cx,cy=s.view_center()
        initial=len(s.world.buildings)
        zoom=s.zoom
        s.touch_began(touch(1,(cx-30,cy)))
        s.touch_began(touch(2,(cx+30,cy)))
        s.touch_moved(touch(2,(cx+80,cy)))
        s.touch_ended(touch(2,(cx+80,cy)))
        s.touch_ended(touch(1,(cx-30,cy)))
        self.assertEqual(len(s.world.buildings),initial)
        self.assertGreater(s.zoom,zoom)

    def test_camera_zoom_keeps_anchor_fixed(self):
        s=self.s
        point=(170,400)
        before=s.screen_to_world(point)
        s.set_zoom(1.4,point)
        after=s.screen_to_world(point)
        self.assertAlmostEqual(before[0],after[0])
        self.assertAlmostEqual(before[1],after[1])

    def test_toolbar_touch_not_used_for_building(self):
        s=self.s
        s.close_overlay()
        s.perform('conveyor')
        initial=len(s.world.buildings)
        button=next(b for b in s.buttons if b['action']=='rotate')
        x,y,w,h=button['rect'];p=(x+w/2,y+h/2)
        s.touch_began(touch(1,p));s.touch_ended(touch(1,p))
        self.assertEqual(s.build_rotation,1)
        self.assertEqual(len(s.world.buildings),initial)

    def test_lifecycle_autosave_and_restore(self):
        s=self.s
        s.close_overlay()
        s.world.step(700)
        s.pause()
        self.assertTrue((self.data/'autosave.json').exists())
        other=self.cls();other.setup()
        self.assertEqual(other.world.digest(),s.world.digest())
        s.accumulator=20;s.resume()
        self.assertEqual(s.accumulator,0)

    def test_manual_save_and_load(self):
        s=self.s
        s.close_overlay()
        s.world.start_wave();s.world.step(250)
        original=s.world.digest()
        s.perform('save')
        s.world.step(300)
        self.assertNotEqual(s.world.digest(),original)
        s.perform('load');s.perform('load')
        self.assertEqual(s.world.digest(),original)

    def test_failed_manual_load_preserves_running_state(self):
        s=self.s
        s.close_overlay()
        original=s.world.digest()
        (self.data/'manual.json').write_text('{"broken":true}')
        with contextlib.redirect_stderr(io.StringIO()):
            s.perform('load');s.perform('load')
        self.assertEqual(s.world.digest(),original)
        self.assertIn('操作エラー',s.message)

    def test_new_demo_backs_up_previous_world(self):
        s=self.s
        s.world.stock['copper']=321
        s.perform('new');s.perform('new')
        self.assertEqual(s.world.stock['copper'],500)
        self.assertEqual(m.World.load(self.data/'before-new.json').stock['copper'],321)

    def test_simulation_pause_still_allows_ui_update(self):
        s=self.s
        s.close_overlay()
        s.perform('pause')
        for _ in range(60):s.update()
        self.assertEqual(s.world.tick_count,0)
        self.assertGreater(s._clock,1)
        s.perform('pause');s.update()
        self.assertEqual(s.world.tick_count,2)

    def test_drag_paints_contiguous_tiles(self):
        s=self.s
        s.close_overlay();s.perform('conveyor')
        p=self.world_point(16.5,12.5)
        q=self.world_point(20.5,12.5)
        s.touch_began(touch(1,p))
        s._clock += m.BUILD_HOLD_SECONDS  # Explicitly arm continuous placement.
        s.touch_moved(touch(1,q))
        s.touch_ended(touch(1,q))
        for x in range(16,21):
            self.assertIsNotNone(s.world.at(x,12))
            self.assertEqual(s.world.at(x,12).kind,'conveyor')

    def test_selected_belt_can_rotate(self):
        s=self.s
        s.close_overlay()
        s.inspect_tile(8,10)
        b=s.world.at(8,10)
        old=b.rotation
        s.perform('rotate')
        self.assertEqual(b.rotation,(old+1)%4)
        s.sync_nodes()
        self.assertAlmostEqual(s.building_nodes[b.id][0].rotation,b.rotation*3.141592653589793/2)


if __name__=='__main__':unittest.main(verbosity=2)
