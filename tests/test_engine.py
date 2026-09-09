# SPDX-License-Identifier: GPL-3.0-only
"""Behavioral regression tests; no third-party packages or iOS needed."""
import copy
import json
import math
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mindustry_pythonista as m


def empty_world():
    w = m.World(32, 24)
    w.sandbox = True
    w.place('core-shard', 2, 2, free=True)
    return w


def load_fixture():
    return json.loads((ROOT/'reference'/'java_fixtures.json').read_text())


class SourceKernelTests(unittest.TestCase):
    def test_120_java_movement_vectors(self):
        for v in load_fixture()['movement']:
            with self.subTest(steps=v['steps'], ys=v['ys']):
                yy, xx = v['ys'], v['xs']
                for _ in range(v['steps']):
                    yy, xx = m.advance_conveyor_positions(yy, xx, v['speed'],
                                                          v['next_minimum'], v['aligned'])
                for a, b in zip(yy, v['expected_y']):
                    self.assertAlmostEqual(a, b, delta=2e-6)
                for a, b in zip(xx, v['expected_x']):
                    self.assertAlmostEqual(a, b, delta=2e-6)

    def test_1344_java_acceptance_vectors(self):
        for v in load_fixture()['acceptance']:
            with self.subTest(v=v):
                result = m.conveyor_accepts(v['minimum'], v['count'], v['incoming'],
                                           v['rotation'], v['rotates'], v['front'])
                self.assertEqual(result, v['expected'])

    def test_40_java_dry_drill_vectors(self):
        for v in load_fixture()['dry_drill']:
            with self.subTest(v=v):
                w = empty_world()
                for x, y in [(10, 10), (11, 10), (10, 11), (11, 11)][:v['count']]:
                    w.ore[w.index(x,y)] = 'copper'
                b = w.place('mechanical-drill', 10, 10, free=True)
                w.step(v['steps'])
                self.assertEqual(w.stats['mined'], v['produced'])
                self.assertAlmostEqual(b.warmup, v['warmup'], delta=2e-6)
                self.assertAlmostEqual(b.progress, v['progress'], delta=.002)

    def test_kernel_does_not_mutate_inputs(self):
        yy, xx = [0, .4], [1, -1]
        m.advance_conveyor_positions(yy, xx, .046)
        self.assertEqual(yy, [0, .4])
        self.assertEqual(xx, [1, -1])

    def test_kernel_rejects_inconsistent_arrays(self):
        with self.assertRaises(ValueError):
            m.advance_conveyor_positions([0], [], .046)


class WorldTests(unittest.TestCase):
    def setUp(self):
        self.w = empty_world()

    def test_multitile_footprint_and_lookup(self):
        b = self.w.cores()[0]
        self.assertEqual(self.w.center(b), (3.5, 3.5))
        for y in range(2,5):
            for x in range(2,5):
                self.assertIs(self.w.at(x,y), b)
        self.assertIsNone(self.w.at(5,5))
        self.assertIsNone(self.w.at(-1,0))

    def test_failed_placement_is_transactional(self):
        self.w.sandbox = False
        self.w.stock['copper'] = 0
        before = self.w.digest()
        self.assertIsNone(self.w.place('duo', 10, 10))
        self.assertEqual(self.w.digest(), before)
        self.assertIsNone(self.w.place('conveyor', 2, 2))
        self.assertEqual(self.w.digest(), before)

    def test_cannot_place_drill_without_ore(self):
        self.assertIsNone(self.w.place('mechanical-drill', 8, 8))

    def test_cannot_build_on_water_or_edge(self):
        self.w.terrain[self.w.index(8,8)] = 2
        self.assertIsNone(self.w.place('conveyor',8,8))
        self.assertIsNone(self.w.place('duo',32,0))
        self.assertIsNone(self.w.place('core-shard',30,22))

    def test_only_one_core(self):
        self.assertIsNone(self.w.place('core-shard',20,10,free=True))

    def test_cost_and_half_refund(self):
        self.w.sandbox = False
        before = self.w.stock['copper']
        b = self.w.place('duo',10,10)
        self.assertEqual(self.w.stock['copper'], before-35)
        self.assertTrue(self.w.remove(b))
        self.assertEqual(self.w.stock['copper'], before-35+17)
        self.assertFalse(self.w.remove(b))

    def test_core_cannot_be_dismantled(self):
        self.assertFalse(self.w.remove(self.w.cores()[0]))
        self.assertFalse(self.w.game_over)

    def test_core_destruction_stops_simulation(self):
        self.w.remove(self.w.cores()[0], refund=False)
        self.assertTrue(self.w.game_over)
        self.w.step(100)
        self.assertEqual(self.w.tick_count, 0)
        self.assertFalse(self.w.start_wave())
        self.assertIsNone(self.w.place('duo',8,8))

    def test_neighbors_are_unique_for_multitile_block(self):
        core = self.w.cores()[0]
        self.w.ore[self.w.index(5,2)] = 'copper'
        drill = self.w.place('mechanical-drill',5,2,free=True)
        self.assertEqual(self.w.neighbors(core), [drill])
        self.assertEqual(self.w.neighbors(drill), [core])

    def test_neighbor_cache_invalidated_on_remove(self):
        core = self.w.cores()[0]
        belt = self.w.place('conveyor',5,3,2,free=True)
        self.assertEqual(self.w.neighbors(core), [belt])
        self.w.remove(belt)
        self.assertEqual(self.w.neighbors(core), [])

    def test_lead_wins_equal_ore_count(self):
        self.w.ore[self.w.index(8,8)] = 'copper'
        self.w.ore[self.w.index(9,8)] = 'lead'
        b = self.w.place('mechanical-drill',8,8,free=True)
        self.assertEqual(self.w.mine_info(b), ('lead',1))

    def test_all_four_rear_input_directions(self):
        for rotation, (dx,dy) in enumerate(m.DIRECTIONS):
            w = empty_world()
            target = w.place('conveyor',10,10,rotation,free=True)
            source = w.place('router',10-dx,10-dy,free=True)
            self.assertTrue(w.receive(target,source,'copper'))
            self.assertEqual(target.belt[0].y,0)
            self.assertFalse(w.receive(target,source,'copper'))

    def test_side_input_and_front_rejection(self):
        target = self.w.place('conveyor',10,10,0,free=True)
        side = self.w.place('router',10,9,free=True)
        front = self.w.place('router',11,10,free=True)
        self.assertFalse(self.w.accepts(target,front,'copper'))
        self.assertTrue(self.w.receive(target,side,'copper'))
        self.assertEqual(target.belt[0].y,.5)
        self.assertEqual(target.belt[0].x,-1)
        self.assertFalse(self.w.receive(target,side,'lead'))

    def test_nonadjacent_input_is_rejected(self):
        a = self.w.place('conveyor',10,10,free=True)
        b = self.w.place('router',8,10,free=True)
        self.assertFalse(self.w.receive(a,b,'copper'))

    def test_capacity_rejects_fourth_item(self):
        b = self.w.place('conveyor',10,10,0,free=True)
        source = self.w.place('router',9,10,free=True)
        b.belt = [m.BeltItem('copper',p) for p in (.2,.6,1)]
        self.assertFalse(self.w.receive(b,source,'copper'))

    def test_dead_end_stops_without_loss(self):
        b = self.w.place('conveyor',10,10,0,free=True)
        b.belt = [m.BeltItem('copper',p) for p in (0,.4,.8)]
        self.w.step(600)
        self.assertEqual(len(b.belt),3)
        for actual, expected in zip([p.y for p in b.belt], [.2,.6,1]):
            self.assertAlmostEqual(actual,expected)

    def test_transport_turns_and_reaches_core(self):
        w = self.w
        b1=w.place('conveyor',7,3,2,free=True)
        b2=w.place('conveyor',6,3,2,free=True)
        b3=w.place('conveyor',5,3,2,free=True)
        source=w.place('router',8,3,free=True)
        start=w.stock['copper']
        self.assertTrue(w.receive(b1,source,'copper'))
        w.step(200)
        self.assertEqual(w.stock['copper'],start+1)
        self.assertEqual(sum(len(b.belt) for b in (b1,b2,b3)),0)

    def test_full_core_applies_backpressure(self):
        w=self.w
        w.stock['copper']=4000
        a=w.place('conveyor',5,3,2,free=True)
        a.belt=[m.BeltItem('copper',0)]
        w.step(200)
        self.assertEqual(len(a.belt),1)
        self.assertEqual(a.belt[0].y,1)
        w.stock['copper']-=1
        w.step()
        self.assertFalse(a.belt)
        self.assertEqual(w.stock['copper'],4000)

    def test_closed_conveyor_loop_conserves_items(self):
        w=self.w
        bs=[w.place('conveyor',10,10,0,free=True),
            w.place('conveyor',11,10,1,free=True),
            w.place('conveyor',11,11,2,free=True),
            w.place('conveyor',10,11,3,free=True)]
        bs[0].belt=[m.BeltItem('copper',.1)]
        w.step(3000)
        self.assertEqual(sum(len(b.belt) for b in bs),1)

    def test_router_delay_only_for_router_output(self):
        w=self.w
        a=w.place('router',10,10,free=True)
        b=w.place('router',11,10,free=True)
        a.inventory={'copper':1}
        w._tick_router(a)
        self.assertEqual(a.inventory,{'copper':1})
        for _ in range(7):
            w._tick_router(a)
        self.assertEqual(b.inventory,{'copper':1})
        self.assertEqual(a.inventory,{})
        w.remove(b)
        belt=w.place('conveyor',11,10,0,free=True)
        a.inventory={'copper':1}
        a.router_time=0
        w._tick_router(a)
        self.assertEqual(len(belt.belt),1)

    def test_demo_moves_copper_to_core_and_ammo(self):
        w=m.World.demo()
        w.sandbox=True
        start=w.stock['copper']
        w.step(3600)
        self.assertGreater(w.stock['copper'],start)
        self.assertGreater(sum(b.ammo for b in w.buildings.values() if b.kind=='duo'),40)
        self.assertGreater(w.stats['mined'],0)

    def test_mined_material_is_conserved(self):
        w=m.World.demo()
        w.sandbox=True
        initial_stock=sum(w.stock.values())
        initial_ammo=sum(b.ammo for b in w.buildings.values())
        w.step(12000)
        stored=sum(w.stock.values())-initial_stock
        in_transit=sum(len(b.belt)+sum(b.inventory.values()) for b in w.buildings.values())
        gun_items=(sum(b.ammo for b in w.buildings.values())-initial_ammo)/2
        self.assertEqual(w.stats['mined'],stored+in_transit+gun_items)

    def test_full_drill_stops_at_capacity(self):
        w=self.w
        w.ore[w.index(10,10)]='copper'
        b=w.place('mechanical-drill',10,10,free=True)
        w.step(30000)
        self.assertEqual(b.inventory,{'copper':10})
        self.assertEqual(w.stats['mined'],10)
        self.assertEqual(b.warmup,0)

    def test_one_copper_becomes_two_ammunition(self):
        gun=self.w.place('duo',10,10,free=True)
        belt=self.w.place('conveyor',9,10,0,free=True)
        self.assertFalse(self.w.receive(gun,belt,'lead'))
        self.assertTrue(self.w.receive(gun,belt,'copper'))
        self.assertEqual(gun.ammo,2)

    def test_no_ammo_means_no_shots(self):
        self.w.place('duo',10,10,free=True)
        self.w.spawn_enemy(15.5,10.5)
        self.w.step(50)
        self.assertEqual(self.w.stats['shots'],0)

    def test_turret_hits_enemy_and_spends_ammo(self):
        gun=self.w.place('duo',10,10,free=True)
        gun.ammo=10
        e=self.w.spawn_enemy(13.5,10.5)
        e.hp=e.max_hp=18
        self.w.step(150)
        self.assertNotIn(e.id,self.w.enemies)
        self.assertGreaterEqual(self.w.stats['kills'],1)
        self.assertLess(gun.ammo,10)

    def test_earliest_segment_hit(self):
        a=m.segment_circle_hit(0,0,10,0,3,0,1)
        b=m.segment_circle_hit(0,0,10,0,7,0,1)
        self.assertAlmostEqual(a,.2)
        self.assertAlmostEqual(b,.6)
        self.assertLess(a,b)
        self.assertIsNone(m.segment_circle_hit(0,0,10,0,4,3,1))
        self.assertEqual(m.segment_circle_hit(0,0,10,0,0,0,1),0)

    def test_fast_bullet_does_not_tunnel(self):
        w=self.w
        e1=w.spawn_enemy(8,10)
        e2=w.spawn_enemy(12,10)
        uid=w.uid()
        w.bullets[uid]=m.Bullet(uid,4,10,12,0,9,60)
        before1,before2=e1.hp,e2.hp
        w._tick_bullets()
        self.assertEqual(e1.hp,before1-9)
        self.assertEqual(e2.hp,before2)
        self.assertFalse(w.bullets)

    def test_sandbox_disables_automatic_waves(self):
        self.w.wave_timer=1
        self.w.step(100)
        self.assertEqual(self.w.wave,0)
        self.assertTrue(self.w.start_wave())
        self.w.step(100)
        self.assertGreater(len(self.w.enemies),0)

    def test_wave_button_does_not_discard_queued_enemies(self):
        self.assertTrue(self.w.start_wave())
        number=self.w.spawn_remaining
        self.assertFalse(self.w.start_wave())
        self.assertEqual(self.w.spawn_remaining,number)

    def test_path_does_not_cross_rock(self):
        w=self.w
        for y in range(w.height):
            w.terrain[w.index(15,y)]=1
        e=w.spawn_enemy(20.5,10.5)
        w.step(200)
        self.assertEqual((e.x,e.y),(20.5,10.5))

    def test_enemy_damages_core(self):
        w=self.w
        e=w.spawn_enemy(5.5,3.5)
        hp=w.cores()[0].hp
        w.step(100)
        self.assertLess(w.cores()[0].hp,hp)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.w=m.World.demo()
        self.w.start_wave()
        self.w.step(180)

    def test_snapshot_roundtrip(self):
        restored=m.World.from_dict(self.w.to_dict())
        self.assertEqual(restored.digest(),self.w.digest())

    def test_continuation_with_enemies_matches(self):
        restored=m.World.from_dict(self.w.to_dict())
        self.w.step(1500)
        restored.step(1500)
        self.assertEqual(restored.digest(),self.w.digest())

    def test_disk_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'save.json'
            self.w.save(path)
            self.assertEqual(m.World.load(path).digest(),self.w.digest())

    def test_failed_write_preserves_existing_save(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'save.json'
            self.w.save(path)
            before=path.read_bytes()
            with patch('mindustry_pythonista.json.dump',side_effect=ValueError('test write failure')):
                with self.assertRaises(ValueError):
                    self.w.save(path)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(len(list(Path(td).glob('*.tmp'))),0)

    def test_rejects_wrong_format_and_schema(self):
        data=self.w.to_dict()
        data['format']='MSAV'
        with self.assertRaises(ValueError):m.World.from_dict(data)
        data=self.w.to_dict()
        data['schema']=999
        with self.assertRaises(ValueError):m.World.from_dict(data)

    def test_rejects_unknown_block(self):
        data=self.w.to_dict()
        data['buildings'][0]['kind']='nuclear-laser'
        with self.assertRaises(ValueError):m.World.from_dict(data)

    def test_rejects_nan(self):
        data=self.w.to_dict()
        data['buildings'][0]['hp']=float('nan')
        with self.assertRaises(ValueError):m.World.from_dict(data)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'nan.json'
            p.write_text('{"bad":NaN}')
            with self.assertRaises(ValueError):m.read_json(p)

    def test_rejects_duplicate_ids(self):
        data=self.w.to_dict()
        data['buildings'][1]['id']=data['buildings'][0]['id']
        with self.assertRaises(ValueError):m.World.from_dict(data)

    def test_rejects_overlapping_buildings(self):
        data=self.w.to_dict()
        data['buildings'][1]['x']=data['buildings'][0]['x']
        data['buildings'][1]['y']=data['buildings'][0]['y']
        with self.assertRaises(ValueError):m.World.from_dict(data)

    def test_rejects_missing_core(self):
        data=self.w.to_dict()
        data['buildings']=[b for b in data['buildings'] if b['kind']!='core-shard']
        with self.assertRaises(ValueError):m.World.from_dict(data)

    def test_destroyed_core_save_is_valid(self):
        self.w.remove(self.w.cores()[0],refund=False)
        restored=m.World.from_dict(self.w.to_dict())
        self.assertTrue(restored.game_over)

    def test_rejects_invalid_inventory(self):
        data=self.w.to_dict()
        b=next(x for x in data['buildings'] if x['kind']=='router')
        b['inventory']={'copper':2}
        with self.assertRaises(ValueError):m.World.from_dict(data)

    def test_rejects_invalid_belt_position(self):
        data=self.w.to_dict()
        b=next(x for x in data['buildings'] if x['kind']=='conveyor')
        b['belt']=[{'item':'copper','y':1.1,'x':0}]
        with self.assertRaises(ValueError):m.World.from_dict(data)

    def test_loaded_data_does_not_alias_original(self):
        data=self.w.to_dict()
        restored=m.World.from_dict(data)
        restored.stock['copper']=0
        restored.ore[0]='lead'
        self.assertNotEqual(self.w.stock['copper'],0)
        self.assertEqual(self.w.ore[0],'')


class ContentTests(unittest.TestCase):
    def test_override_numeric_values(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'content_overrides.json'
            p.write_text('{"duo":{"damage":27},"conveyor":{"speed":0.08}}')
            content=m.load_content(p)
            self.assertEqual(content['duo']['damage'],27)
            self.assertEqual(content['conveyor']['speed'],.08)
            self.assertEqual(m.DEFAULT_CONTENT['duo']['damage'],9)

    def test_invalid_mod_keys_and_structural_changes_rejected(self):
        for patch_value in ({'duo':{'size':2}}, {'nonsense':{}}, {'duo':{'damage':-1}},
                            {'conveyor':{'speed':9}}, {'duo':{'health':0}}):
            with self.subTest(patch=patch_value), tempfile.TemporaryDirectory() as td:
                p=Path(td)/'content_overrides.json'
                p.write_text(json.dumps(patch_value))
                with self.assertRaises(ValueError):m.load_content(p)

    def test_save_retains_content_snapshot(self):
        content=copy.deepcopy(m.DEFAULT_CONTENT)
        content['duo']['damage']=18
        w=m.World.demo(content)
        restored=m.World.from_dict(w.to_dict())
        self.assertEqual(restored.content['duo']['damage'],18)


if __name__=='__main__':
    unittest.main(verbosity=2)
