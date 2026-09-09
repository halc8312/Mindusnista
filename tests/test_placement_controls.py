# SPDX-License-Identifier: GPL-3.0-only
"""Placement input regressions using doubles, NOT Pythonista/iPhone execution."""
import copy
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


class PlacementControlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patcher = patch('mindustry_pythonista.data_directory',
                             return_value=Path(self.tmp.name))
        self.patcher.start()
        self.s = self.new_scene()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def new_scene(self):
        s = m.make_scene_class(scene, ui)()
        s.setup()
        self.assertFalse(s._failed)
        s.close_overlay()
        return s

    def point(self, x, y):
        s = self.s
        cx, cy = s.view_center()
        return (cx+(x-s.camera_x)*m.TILE*s.zoom,
                cy+(y-s.camera_y)*m.TILE*s.zoom)

    def press(self, action, tid=99, overlay=False):
        buttons = self.s.overlay_buttons if overlay else self.s.buttons
        button = next(b for b in buttons if b['action'] == action)
        x, y, w, h = button['rect']
        p = (x+w/2, y+h/2)
        self.s.touch_began(touch(tid, p))
        self.s.touch_ended(touch(tid, p))

    def enable_position(self, tool='conveyor'):
        self.s.perform(tool)
        self.s.perform('position-mode')

    def test_position_mode_reuses_six_buttons_and_three_rows(self):
        s = self.s
        self.assertFalse(s.position_mode)
        s.perform('conveyor')
        self.assertIn('position-mode', [b['action'] for b in s.buttons])
        self.assertNotIn('wave', [b['action'] for b in s.buttons])
        self.assertIn('direction-0', [b['action'] for b in s.buttons])
        self.press('direction-3')
        self.press('position-mode')
        self.assertTrue(s.position_mode)
        expected = ['rotate', 'move-2', 'move-1', 'move-3', 'move-0', 'place-preview']
        for width, height in ((320, 568), (390, 844), (568, 320), (844, 390)):
            with self.subTest(size=(width, height)):
                s.size = SimpleNamespace(w=width, h=height)
                s.did_change_size()
                self.assertEqual(len(s.buttons), 16)
                self.assertEqual(len({b['rect'][1] for b in s.buttons}), 3)
                controls = [b for b in s.buttons if b['action'] in expected]
                self.assertEqual([b['action'] for b in controls], expected)
                for b in controls:
                    x, y, w, h = b['rect']
                    self.assertGreaterEqual(w, 44)
                    self.assertGreaterEqual(h, 44)
                    self.assertGreaterEqual(x, 0)
                    self.assertGreaterEqual(y, 0)
                    self.assertLessEqual(x+w, width)
                    self.assertLessEqual(y+h, height)
                for left, right in zip(controls, controls[1:]):
                    self.assertLess(left['rect'][0]+left['rect'][2], right['rect'][0])
        self.press('position-mode')
        self.assertFalse(s.position_mode)
        self.assertEqual(s.build_rotation, 3)
        self.assertIn('direction-3', [b['action'] for b in s.buttons])
        self.assertIn('rotate-cw', [b['action'] for b in s.buttons])

    def test_wave_remains_reachable_and_position_control_is_for_build_tools(self):
        s = self.s
        for tool in m.BUILD_TOOLS:
            s.perform(tool)
            self.assertIn('position-mode', [b['action'] for b in s.buttons])
        for tool in ('pan', 'erase'):
            s.perform(tool)
            self.assertNotIn('position-mode', [b['action'] for b in s.buttons])
            self.assertIn('wave', [b['action'] for b in s.buttons])
        s.perform('conveyor')
        self.press('menu')
        self.assertIn('wave', [b['action'] for b in s.overlay_buttons])
        old_wave = s.world.wave
        self.press('wave', overlay=True)
        self.assertEqual(s.world.wave, old_wave+1)

    def test_directional_nudges_only_move_the_candidate_one_tile(self):
        s = self.s
        self.enable_position()
        s.highlight(17, 12)
        s.build_rotation = 3
        before = s.world.to_dict()
        for rotation, (dx, dy) in enumerate(m.DIRECTIONS):
            previous = s.preview_tile
            self.press('move-%d' % rotation)
            self.assertEqual(s.preview_tile, (previous[0]+dx, previous[1]+dy))
            self.assertEqual(s.world.to_dict(), before)
            self.assertEqual(s.build_rotation, 3)
        self.assertEqual(s.preview_tile, (17, 12))

    def test_nudges_clamp_the_whole_footprint_and_follow_offscreen_candidate(self):
        s = self.s
        self.enable_position('mechanical-drill')
        size = s.world.content[s.tool]['size']
        self.assertGreater(size, 1)
        s.highlight(0, 0)
        self.press('move-2')
        self.press('move-3')
        self.assertEqual(s.preview_tile, (0, 0))
        far = (s.world.width-size, s.world.height-size)
        s.highlight(*far)
        self.press('move-0')
        self.press('move-1')
        self.assertEqual(s.preview_tile, far)
        p = self.point(far[0]+size/2, far[1]+size/2)
        self.assertGreaterEqual(p[0], 0)
        self.assertLessEqual(p[0], s.size.w)
        self.assertTrue(s.is_world_point(p))

    def test_position_map_tap_and_slide_are_preview_only(self):
        s = self.s
        self.enable_position()
        before = s.world.to_dict()
        p, q = self.point(16.5, 12.5), self.point(20.5, 12.5)
        s.touch_began(touch(1, p))
        s.touch_ended(touch(1, p))
        self.assertEqual(s.preview_tile, (16, 12))
        self.assertEqual(s.world.to_dict(), before)
        s.touch_began(touch(1, p))
        s._clock += .36
        s.touch_moved(touch(1, q))
        s.touch_ended(touch(1, q))
        self.assertEqual(s.preview_tile, (20, 12))
        self.assertEqual(s.world.to_dict(), before)

    def test_place_button_commits_candidate_once_with_normal_cost(self):
        s = self.s
        self.enable_position()
        s.highlight(17, 12)
        s.perform('rotate')
        copper = s.world.stock['copper']
        count = len(s.world.buildings)
        self.press('place-preview')
        b = s.world.at(17, 12)
        self.assertIsNotNone(b)
        self.assertEqual(b.rotation, 1)
        self.assertEqual(s.world.stock['copper'], copper-1)
        self.assertEqual(len(s.world.buildings), count+1)
        self.press('place-preview')
        self.assertIs(s.world.at(17, 12), b)
        self.assertEqual(s.world.stock['copper'], copper-1)

    def test_place_button_reorients_existing_belt_without_cargo_or_hp_loss(self):
        s = self.s
        b = s.world.place('conveyor', 17, 12, 0, free=True)
        b.belt = [m.BeltItem('copper', .25, -.1), m.BeltItem('lead', .7, .1)]
        b.hp = 31
        before = copy.deepcopy(m.asdict(b))
        stock = copy.deepcopy(s.world.stock)
        self.enable_position()
        s.highlight(17, 12)
        s.perform('rotate')
        self.press('place-preview')
        self.assertEqual(b.rotation, 1)
        after = m.asdict(b)
        after['rotation'] = before['rotation']
        self.assertEqual(after, before)
        self.assertEqual(s.world.stock, stock)
        self.assertIs(s.world.at(17, 12), b)

    def test_position_actions_cancel_old_map_touches_before_release(self):
        for action in ('position-mode', 'move-0', 'place-preview'):
            with self.subTest(action=action):
                self.s = s = self.new_scene()
                self.enable_position()
                p = self.point(17.5, 12.5)
                s.touch_began(touch(1, p))
                s.perform(action)
                self.assertFalse(s.gestures)
                before_release = s.world.to_dict()
                s.touch_ended(touch(1, p))
                self.assertEqual(s.world.to_dict(), before_release)

    def test_early_slide_cannot_paint_or_erase_even_after_waiting(self):
        for tool in ('conveyor', 'copper-wall', 'erase'):
            with self.subTest(tool=tool):
                self.s = s = self.new_scene()
                if tool == 'erase':
                    for x in range(16, 21):
                        s.world.place('conveyor', x, 12, 0, free=True)
                s.perform(tool)
                before = s.world.to_dict()
                p, q, r = [self.point(x+.5, 12.5) for x in (16, 18, 20)]
                s.touch_began(touch(1, p))
                s._clock += .1
                s.touch_moved(touch(1, q))
                s._clock += 1
                s.touch_moved(touch(1, r))
                s.touch_ended(touch(1, r))
                self.assertEqual(s.world.to_dict(), before)

    def test_hold_then_slide_keeps_contiguous_build_and_erase(self):
        for tool in ('conveyor', 'copper-wall', 'erase'):
            with self.subTest(tool=tool):
                self.s = s = self.new_scene()
                if tool == 'erase':
                    for x in range(16, 21):
                        s.world.place('conveyor', x, 12, 0, free=True)
                s.perform(tool)
                p, q = self.point(16.5, 12.5), self.point(20.5, 12.5)
                s.touch_began(touch(1, p))
                s._clock += .36
                s.touch_moved(touch(1, q))
                s.touch_ended(touch(1, q))
                for x in range(16, 21):
                    if tool == 'erase':
                        self.assertIsNone(s.world.at(x, 12))
                    else:
                        self.assertEqual(s.world.at(x, 12).kind, tool)

    def test_movement_before_hold_threshold_cancels_this_touch(self):
        s = self.s
        s.perform('conveyor')
        before = s.world.to_dict()
        p, q = self.point(16.5, 12.5), self.point(18.5, 12.5)
        s.touch_began(touch(1, p))
        s._clock += .349
        s.touch_moved(touch(1, q))
        s.touch_ended(touch(1, q))
        self.assertEqual(s.world.to_dict(), before)

    def test_large_release_jump_without_move_event_does_not_build(self):
        s = self.s
        s.perform('conveyor')
        before = s.world.to_dict()
        s.touch_began(touch(1, self.point(16.5, 12.5)))
        s.touch_ended(touch(1, self.point(20.5, 12.5)))
        self.assertEqual(s.world.to_dict(), before)

    def test_small_jitter_across_low_zoom_tile_edge_taps_start_tile(self):
        s = self.s
        s.perform('conveyor')
        s.set_zoom(.25)
        p, q = self.point(17.96, 12.5), self.point(18.04, 12.5)
        self.assertLess(abs(q[0]-p[0]), 7)
        s.touch_began(touch(1, p))
        s.touch_moved(touch(1, q))
        s.touch_ended(touch(1, q))
        self.assertIsNotNone(s.world.at(17, 12))
        self.assertIsNone(s.world.at(18, 12))

    def test_leaving_viewport_cancels_even_if_touch_returns_after_hold(self):
        for edge in ('toolbar', 'left', 'right'):
            with self.subTest(edge=edge):
                self.s = s = self.new_scene()
                s.perform('conveyor')
                before = s.world.to_dict()
                p, q = self.point(16.5, 12.5), self.point(18.5, 12.5)
                outside = {'toolbar': (p[0], s.bar_top+5),
                           'left': (-10, p[1]),
                           'right': (s.size.w+10, p[1])}[edge]
                s.touch_began(touch(1, p))
                s._clock += .36
                s.touch_moved(touch(1, outside))
                s.touch_moved(touch(1, q))
                s.touch_ended(touch(1, q))
                self.assertEqual(s.world.to_dict(), before)

    def test_pinch_resize_menu_and_pause_cancel_held_placement(self):
        for action in ('pinch', 'resize', 'menu', 'pause', 'background'):
            with self.subTest(action=action):
                self.s = s = self.new_scene()
                s.perform('conveyor')
                before = s.world.to_dict()
                p, q = self.point(16.5, 12.5), self.point(18.5, 12.5)
                s.touch_began(touch(1, p))
                s._clock += .36
                if action == 'pinch':
                    s.touch_began(touch(2, q))
                    s.touch_ended(touch(2, q))
                elif action == 'resize':
                    s.size = SimpleNamespace(w=844, h=390)
                    s.did_change_size()
                    q = self.point(18.5, 12.5)
                elif action == 'background':
                    s.pause()
                else:
                    s.perform(action)
                s.touch_moved(touch(1, q))
                s.touch_ended(touch(1, q))
                self.assertEqual(s.world.to_dict(), before)


    def test_update_shows_ready_after_stationary_hold_without_placing_early(self):
        s = self.s
        s.perform('conveyor')
        s.sim_paused = True
        p = self.point(17.5, 12.5)
        before = s.world.to_dict()
        copper = s.world.stock['copper']
        count = len(s.world.buildings)
        s.touch_began(touch(1, p))
        s.dt = .1
        for _ in range(3):
            s.update()
        self.assertNotIn('連続設置OK', s.message_label.text)
        s.dt = .05
        s.update()
        self.assertFalse(s._failed)
        self.assertIn('連続設置OK', s.message_label.text)
        self.assertEqual(s.world.to_dict(), before)
        s.touch_ended(touch(1, p))
        self.assertIsNotNone(s.world.at(17, 12))
        self.assertEqual(len(s.world.buildings), count+1)
        self.assertEqual(s.world.stock['copper'], copper-1)

    def test_failed_position_placement_preserves_world_and_displays_reason(self):
        for failure, expected in (('resources', '銅が足りません'),
                                  ('outside', 'マップの外です'),
                                  ('occupied', '別の建物があります')):
            with self.subTest(failure=failure):
                self.s = s = self.new_scene()
                self.enable_position()
                tile = (17, 12)
                if failure == 'resources':
                    s.world.stock['copper'] = 0
                elif failure == 'outside':
                    tile = (-1, 12)
                else:
                    self.assertIsNotNone(s.world.place('router', *tile, free=True))
                s.highlight(*tile)
                s.refresh_hud()
                self.assertIn('マス操作', s.message_label.text)
                before = s.world.to_dict()
                self.press('place-preview')
                s.refresh_hud()
                self.assertEqual(s.world.to_dict(), before)
                self.assertIn(expected, s.message_label.text)
                self.assertNotIn('マス操作', s.message_label.text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
