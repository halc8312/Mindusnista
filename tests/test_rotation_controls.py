# SPDX-License-Identifier: GPL-3.0-only
"""0.1.2 rotation input regressions. Test doubles, NOT real iOS execution."""
import copy
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mindustry_pythonista as m
from pythonista_stub import scene, ui, touch


class RotationControlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.patcher = patch('mindustry_pythonista.data_directory', return_value=self.data)
        self.patcher.start()
        self.s = m.make_scene_class(scene, ui)()
        self.s.setup()
        self.assertFalse(self.s._failed)
        self.s.close_overlay()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def point(self, x, y):
        s = self.s
        cx, cy = s.view_center()
        return cx+(x-s.camera_x)*m.TILE*s.zoom, cy+(y-s.camera_y)*m.TILE*s.zoom

    def button(self, action, overlay=False):
        buttons = self.s.overlay_buttons if overlay else self.s.buttons
        return next(b for b in buttons if b['action'] == action)

    def press(self, action, tid=99, overlay=False):
        x, y, w, h = self.button(action, overlay)['rect']
        p = (x+w/2, y+h/2)
        self.s.touch_began(touch(tid, p))
        self.s.touch_ended(touch(tid, p))

    def tap(self, x, y, tid=1):
        p = self.point(x+.5, y+.5)
        self.assertTrue(self.s.is_world_point(p))
        self.s.touch_began(touch(tid, p))
        self.s.touch_ended(touch(tid, p))

    def select_belt(self):
        s = self.s
        s.perform('pan')
        s.inspect_tile(8, 10)
        b = s.world.at(8, 10)
        self.assertEqual(b.kind, 'conveyor')
        return b

    def test_each_direction_button_sets_new_belt_orientation(self):
        s = self.s
        s.perform('conveyor')
        for rotation in range(4):
            with self.subTest(rotation=rotation):
                self.press('direction-%d' % rotation)
                self.tap(16+rotation, 12)
                self.assertEqual(s.world.at(16+rotation, 12).rotation, rotation)
                self.assertEqual(s.direction_label.text, m.ARROWS[rotation])

    def test_left_and_right_are_opposites_in_world_coordinates(self):
        s = self.s
        s.perform('conveyor')
        self.press('rotate')
        self.assertEqual(s.build_rotation, 1)  # east -> north
        self.press('rotate-cw')
        self.assertEqual(s.build_rotation, 0)
        self.press('rotate-cw')
        self.assertEqual(s.build_rotation, 3)  # east -> south

    def test_four_turns_restore_each_starting_direction(self):
        s = self.s
        s.perform('conveyor')
        for start in range(4):
            for action in ('rotate', 'rotate-cw'):
                s.build_rotation = start
                for _ in range(4):
                    self.press(action)
                self.assertEqual(s.build_rotation, start)

    def test_rotation_buttons_never_create_or_charge_buildings(self):
        s = self.s
        s.perform('conveyor')
        before = s.world.to_dict()
        for action in ('rotate', 'rotate-cw', 'direction-0', 'direction-1', 'direction-2', 'direction-3'):
            self.press(action)
        self.assertEqual(s.world.to_dict(), before)

    def test_preview_visible_before_placement_and_updates_immediately(self):
        s = self.s
        before = len(s.world.buildings)
        s.perform('conveyor')
        self.assertGreater(s.ghost_node.alpha, 0)
        self.assertGreater(s.direction_marker.alpha, 0)
        self.press('direction-3')
        self.assertEqual(s.direction_label.text, '↓')
        self.assertAlmostEqual(s.ghost_node.rotation, 3*math.pi/2)
        self.assertEqual(len(s.world.buildings), before)

    def test_preview_only_is_not_saved_as_a_building(self):
        s = self.s
        before = len(s.world.buildings)
        s.perform('conveyor')
        self.press('direction-2')
        s.save_world(manual=True)
        self.assertEqual(len(m.World.load(self.data/'manual.json').buildings), before)

    def test_second_finger_can_rotate_while_first_holds_placement(self):
        s = self.s
        s.perform('conveyor')
        p = self.point(17.5, 12.5)
        before = s.world.stock['copper']
        s.touch_began(touch(1, p))
        self.press('direction-1', tid=2)
        self.assertFalse(s.gestures[1]['pinched'])
        self.assertIsNone(s.world.at(17, 12))
        s.touch_ended(touch(1, p))
        self.assertEqual(s.world.at(17, 12).rotation, 1)
        self.assertEqual(s.world.stock['copper'], before-1)

    def test_selected_rotation_uses_building_direction_not_stale_build_direction(self):
        s = self.s
        b = self.select_belt()
        b.rotation = 2
        s.build_rotation = 0
        self.press('rotate-cw')
        self.assertEqual(b.rotation, 1)
        self.assertEqual(s.build_rotation, 1)
        self.assertEqual(s.direction_label.text, '↑')

    def test_selected_direct_rotation_preserves_cargo_hp_id_and_resources(self):
        s = self.s
        b = self.select_belt()
        b.belt = [m.BeltItem('copper', .1, -.2), m.BeltItem('lead', .7, .1)]
        b.hp = 31
        before = copy.deepcopy(m.asdict(b))
        stock = copy.deepcopy(s.world.stock)
        count = len(s.world.buildings)
        self.press('direction-3')
        after = m.asdict(b)
        after['rotation'] = before['rotation']
        self.assertEqual(after, before)
        self.assertEqual(s.world.stock, stock)
        self.assertEqual(len(s.world.buildings), count)
        self.assertIs(s.world.at(b.x, b.y), b)

    def test_tap_existing_belt_reorients_without_cost_or_rebuild(self):
        s = self.s
        b = s.world.place('conveyor', 17, 12, 0, free=True)
        b.belt = [m.BeltItem('copper', .5, -.1)]
        before = copy.deepcopy(m.asdict(b))
        stock = copy.deepcopy(s.world.stock)
        s.perform('conveyor')
        self.press('direction-2')
        self.tap(17, 12)
        self.assertEqual(b.rotation, 2)
        after = m.asdict(b)
        after['rotation'] = before['rotation']
        self.assertEqual(after, before)
        self.assertEqual(s.world.stock, stock)
        self.assertIs(s.world.at(17, 12), b)

    def test_drag_across_existing_belt_does_not_reorient_it(self):
        s = self.s
        b = s.world.place('conveyor', 18, 12, 2, free=True)
        s.perform('conveyor')
        self.press('direction-1')
        p, q = self.point(16.5, 12.5), self.point(20.5, 12.5)
        s.touch_began(touch(1, p))
        s.touch_moved(touch(1, q))
        s.touch_ended(touch(1, q))
        self.assertEqual(b.rotation, 2)
        for x in (16, 17, 19, 20):
            self.assertEqual(s.world.at(x, 12).rotation, 1)

    def test_rotate_during_drag_applies_to_next_new_tiles(self):
        s = self.s
        s.perform('conveyor')
        p, q, r = self.point(16.5,12.5), self.point(18.5,12.5), self.point(20.5,12.5)
        s.touch_began(touch(1, p))
        s.touch_moved(touch(1, q))
        self.press('direction-3', tid=2)
        s.touch_moved(touch(1, r))
        s.touch_ended(touch(1, r))
        self.assertEqual([s.world.at(x,12).rotation for x in range(16,21)], [0,0,0,3,3])

    def test_direction_choice_highlight_matches_selected_belt(self):
        s = self.s
        b = self.select_belt()
        b.rotation = 3
        s.build_rotation = 0
        s.refresh_hud()
        self.assertNotEqual(self.button('direction-3')['bg'].color,
                            self.button('direction-0')['bg'].color)
        self.assertEqual(self.button('direction-3')['bg'].alpha, 1)

    def test_disabled_controls_do_not_change_nondirectional_building(self):
        s = self.s
        for tool in ('mechanical-drill', 'duo', 'router', 'copper-wall', 'erase', 'pan'):
            s.perform(tool)
            before = s.world.to_dict()
            rotation = s.build_rotation
            self.press('rotate-cw')
            self.press('direction-1')
            self.assertEqual(s.world.to_dict(), before)
            self.assertEqual(s.build_rotation, rotation)
            self.assertLess(self.button('rotate')['bg'].alpha, 1)

    def test_inspecting_non_belt_cannot_change_a_stale_belt_selection(self):
        s = self.s
        b = self.select_belt()
        before = b.rotation
        core = s.world.cores()[0]
        s.inspect_tile(core.x, core.y)
        self.press('direction-%d' % ((before+1)%4))
        self.assertEqual(b.rotation, before)
        self.assertIsNone(s.rotation_target())

    def test_removed_selection_cannot_rotate_another_building(self):
        s = self.s
        b = self.select_belt()
        s.world.remove(b)
        before = s.world.to_dict()
        self.press('rotate')
        self.assertEqual(s.world.to_dict(), before)
        self.assertFalse(s._failed)

    def test_switching_tool_hides_preview_and_cancels_pending_placement(self):
        s = self.s
        s.perform('conveyor')
        p = self.point(17.5,12.5)
        s.touch_began(touch(1,p))
        self.press('pan', tid=2)
        s.touch_ended(touch(1,p))
        self.assertIsNone(s.world.at(17,12))
        self.assertEqual(s.ghost_node.alpha, 0)
        self.assertEqual(s.direction_marker.alpha, 0)

    def test_opening_menu_cancels_placement_without_charge(self):
        s = self.s
        s.perform('conveyor')
        p = self.point(17.5,12.5)
        before = s.world.stock['copper']
        s.touch_began(touch(1,p))
        self.press('menu', tid=2)
        s.touch_ended(touch(1,p))
        self.assertEqual(s.world.stock['copper'],before)
        self.assertIsNone(s.world.at(17,12))

    def test_zoom_keeps_direction_badge_screen_size_constant(self):
        s = self.s
        s.perform('conveyor')
        for zoom in (.25,.5,1,2.5):
            s.set_zoom(zoom)
            self.assertAlmostEqual(s.root.x_scale*s.direction_marker.x_scale,1)
            self.assertAlmostEqual(s.root.y_scale*s.direction_marker.y_scale,1)

    def test_all_rotation_hit_targets_at_least_44_points_and_nonoverlapping(self):
        s = self.s
        for width,height in ((320,568),(375,667),(390,844),(430,932),(568,320),(844,390),(1024,768)):
            s.size = SimpleNamespace(w=width,h=height)
            s.did_change_size()
            self.assertFalse(s._failed)
            buttons = [b for b in s.buttons if b['action'] in ('rotate','rotate-cw') or b['action'].startswith('direction-')]
            self.assertEqual(len(buttons),6)
            for b in buttons:
                x,y,w,h = b['rect']
                self.assertGreaterEqual(w,44)
                self.assertGreaterEqual(h,44)
                self.assertGreaterEqual(x,0)
                self.assertGreaterEqual(y,0)
                self.assertLessEqual(x+w,width)
                self.assertLessEqual(y+h,height)
            ordered = sorted(buttons,key=lambda b:b['rect'][0])
            for left,right in zip(ordered,ordered[1:]):
                self.assertLess(left['rect'][0]+left['rect'][2],right['rect'][0])

    def test_direction_badge_stays_inside_viewport_at_center(self):
        s = self.s
        for width,height in ((320,568),(390,844),(568,320),(844,390)):
            s.size = SimpleNamespace(w=width,h=height)
            s.did_change_size()
            s.perform('conveyor')
            x,y = s.direction_marker.position
            cx,cy = s.view_center()
            screen_x = cx+(x-s.camera_x*m.TILE)*s.zoom
            screen_y = cy+(y-s.camera_y*m.TILE)*s.zoom
            self.assertGreaterEqual(screen_x-17,0)
            self.assertLessEqual(screen_x+17,width)
            self.assertGreaterEqual(screen_y-14,s.bar_top+24-1e-6)
            self.assertLessEqual(screen_y+14,height-s.header_height+1e-6)

    def test_menu_and_controls_fit_small_portrait_and_landscape(self):
        s = self.s
        for width,height in ((320,568),(568,320),(844,390),(390,844)):
            s.size = SimpleNamespace(w=width,h=height)
            s.did_change_size()
            for kind in ('menu','controls','help'):
                s.show_overlay(kind)
                for b in s.overlay_buttons:
                    x,y,w,h = b['rect']
                    self.assertGreaterEqual(x,0)
                    self.assertGreaterEqual(y,0)
                    self.assertLessEqual(x+w,width)
                    self.assertLessEqual(y+h,height)

    def test_relocated_speed_and_zoom_buttons_are_reachable_and_work(self):
        s = self.s
        self.press('menu')
        self.press('controls', overlay=True)
        self.assertEqual(s.overlay_kind,'controls')
        self.press('speed', overlay=True)
        self.assertEqual(s.sim_speed,2)
        self.assertIn('2', self.button('speed',True)['label'].text)
        zoom = s.zoom
        self.press('zoom-in', overlay=True)
        self.assertGreater(s.zoom,zoom)
        self.press('zoom-out', overlay=True)
        self.assertAlmostEqual(s.zoom,zoom)
        s.camera_x = 30
        self.press('home', overlay=True)
        self.assertEqual((s.camera_x,s.camera_y),s.world.center(s.world.cores()[0]))
        self.press('close', overlay=True)
        self.assertIsNone(s.overlay_kind)

    def test_resizing_retains_rotation_but_cancels_touches(self):
        s = self.s
        s.perform('conveyor')
        self.press('direction-3')
        p = self.point(17.5,12.5)
        s.touch_began(touch(1,p))
        s.size = SimpleNamespace(w=844,h=390)
        s.did_change_size()
        self.assertEqual(s.build_rotation,3)
        self.assertFalse(s.gestures)
        self.assertEqual(s.direction_label.text,'↓')

    def test_rotated_cargo_save_and_resume_is_lossless(self):
        s = self.s
        b = self.select_belt()
        b.belt = [m.BeltItem('copper',.2,-.1),m.BeltItem('lead',.75,.05)]
        self.press('direction-1')
        s.save_world(manual=True)
        restored = m.World.load(self.data/'manual.json')
        self.assertEqual(m.asdict(restored.buildings[b.id]),m.asdict(b))
        self.assertEqual(restored.digest(),s.world.digest())

    def test_old_011_metadata_save_loads_without_schema_change(self):
        s = self.s
        data = s.world.to_dict()
        data['port_version'] = '0.1.1-dev'
        path = self.data/'manual.json'
        m.atomic_json(path,data)
        before = s.world.digest()
        s.perform('load');s.perform('load')
        self.assertEqual(s.world.digest(),before)
        self.assertEqual(m.SAVE_VERSION,1)

    def test_reorientation_updates_sprite_and_output_neighbor(self):
        s = self.s
        b = self.select_belt()
        self.press('direction-3')
        s.sync_nodes()
        self.assertAlmostEqual(s.building_nodes[b.id][0].rotation,3*math.pi/2)
        dx,dy = m.DIRECTIONS[b.rotation]
        self.assertEqual((dx,dy),(0,-1))
        self.assertEqual(s.world.front(b),s.world.at(b.x,b.y-1))

    def test_ui_runs_300_frames_after_rotation_and_overlay_changes(self):
        s = self.s
        s.perform('conveyor')
        self.press('direction-1')
        self.tap(17,12)
        self.press('menu');self.press('controls',overlay=True);self.press('close',overlay=True)
        for _ in range(300):
            s.update()
        self.assertFalse(s._failed)
        self.assertEqual(s.world.tick_count,600)


if __name__ == '__main__':
    unittest.main(verbosity=2)
