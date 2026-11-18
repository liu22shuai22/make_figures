import math
from pathlib import Path
import unittest
from unittest.mock import patch

from api import render_in_worker
import er_generator as er


class LayoutTests(unittest.TestCase):
    def test_crowded_overview_adds_spacing_within_page_width(self):
        model = er.normalize_spec({
            "entities": [{"name": "A"}, {"name": "B"}],
            "relations": [{"a": "A", "b": "B", "card": "1:n"}],
        })
        model.update(ent_w=[0.8, 0.8], rel_w=[0.8], attr_w=[[]])
        _, connections = er.overview_topology(model)
        scene = er._planar_scene(model, {("e", 0): (-0.88, 0), ("d", 0): (0, 0),
                                        ("e", 1): (0.88, 0)}, connections)
        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            scene["labels"] = er.layout_cardinality_labels(model, scene, scene["paths"])
            x0, x1, *_ = er._diagram_extents(scene["boxes"], scene["paths"], scene["labels"])
            result = er._ease_overview_spacing(model, scene, None, math.inf)
            self.assertIs(er._ease_overview_spacing(model, scene, x1 - x0, math.inf), scene)

        self.assertGreater(math.dist(*result["ents"][:2]), math.dist(*scene["ents"][:2]))
        self.assertEqual([box[2:] for box in result["boxes"]], [box[2:] for box in scene["boxes"]])
        self.assertEqual(sum(map(er._path_bends, result["paths"])), 0)
        self.assertTrue(er._clear_planar_geometry(result))
        self.assertEqual(er._cardinality_conflicts(result["boxes"], result["paths"], result["labels"]), 0)

    def test_portrait_overview_rotates_coordinates_and_keeps_shapes_upright(self):
        model = er.normalize_spec({
            "entities": [{"name": "A"}, {"name": "B"}],
            "relations": [{"a": "A", "b": "B", "card": "1:n"}],
        })
        model.update(ent_w=[1.2, 1.4], rel_w=[0.9], attr_w=[[]])
        _, connections = er.overview_topology(model)
        positions = {("e", 0): (0, -3), ("d", 0): (0, 0), ("e", 1): (0, 3)}
        scene = er._planar_scene(model, positions, connections)
        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            scene["labels"] = er.layout_cardinality_labels(model, scene, scene["paths"])
            result = er._orient_overview_landscape(model, scene, math.inf)
        left, right, top, bottom = er._diagram_extents(result["boxes"], result["paths"], result["labels"])
        self.assertGreaterEqual(right - left, er.OVERVIEW_LANDSCAPE_RATIO * (bottom - top))
        self.assertEqual([box[2:] for box in result["boxes"]], [box[2:] for box in scene["boxes"]])
        self.assertEqual([seg[4:] for seg in result["segs"]], [seg[4:] for seg in scene["segs"]])
        self.assertTrue(er._clear_planar_geometry(result))
        self.assertEqual(er._cardinality_conflicts(result["boxes"], result["paths"], result["labels"]), 0)

    def test_final_geometry_rejects_self_relation_bend_inside_own_diamond(self):
        model = er.normalize_spec({
            "entities": [{"name": "Folder"}],
            "relations": [{"name": "Contains", "a": "Folder", "b": "Folder"}],
        })
        model.update(ent_w=[0.8], rel_w=[0.86], attr_w=[[]])
        _, connections = er.overview_topology(model)
        positions = {("e", 0): (0, 2), ("d", 0): (0, 0), ("bend", 0): (0.1, 0.1)}
        invalid = er._planar_scene(model, positions, connections)
        self.assertGreater(er.overview_quality(invalid, invalid["paths"])[1], 0)
        self.assertFalse(er._clear_planar_geometry(invalid))
        valid = er._planar_scene(model, {**positions, ("bend", 0): (1, 1)}, connections)
        self.assertTrue(er._clear_planar_geometry(valid))

    def test_avoid_touching_or_visually_merging_at_route_waypoints(self):
        elbow = er._path_segments(((-2, 1), (0, 0), (2, 1)))
        for y in (0, -0.012):
            nearby = er._path_segments(((-1, y), (0, y), (1, y)))
            self.assertTrue(er._routes_conflict(elbow, nearby))
        clear = er._path_segments(((-1, -0.10), (1, -0.10)))
        self.assertFalse(er._routes_conflict(elbow, clear))
        shared_port = er._path_segments(((-2, 1), (-3, 0)))
        self.assertFalse(er._routes_conflict(elbow, shared_port))

    def test_axis_compaction_moves_waypoints_with_their_connected_shapes(self):
        model = er.normalize_spec({
            "entities": [{"name": "A"}, {"name": "B"}],
            "relations": [{"a": "A", "b": "B"}],
        })
        model.update(ent_w=[0.62] * 2, rel_w=[er.DW], attr_w=[[]])
        _, connections = er.overview_topology(model)
        scene = er._planar_scene(model, {("e", 0): (-8, 0), ("d", 0): (0, 0),
                                        ("e", 1): (8, 0)}, connections)
        _, edges = er._overview_edges(scene)
        _, _, source, target, _ = edges[0]
        waypoint = (-4, 0.8)
        scene["paths"][0] = er._visible_path((source[:2], waypoint, target[:2]), source, target)
        mapping = er._axis_compaction_targets(scene, 0, 0.5, math.inf)
        self.assertAlmostEqual(mapping[waypoint][0], -2)
        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            scene["labels"] = er.layout_cardinality_labels(model, scene, scene["paths"])
            compact = er._squeeze_verified_overview(model, scene, None, math.inf)
        self.assertTrue(er._clear_planar_geometry(compact))
        self.assertEqual(er._cardinality_conflicts(compact["boxes"], compact["paths"], compact["labels"]), 0)
        self.assertLess(er._planar_readability(compact, None)[2], er._planar_readability(scene, None)[2])
        self.assertLessEqual(sum(map(er._path_bends, compact["paths"])), 1)

    def test_wide_connected_layout_keeps_shared_entities(self):
        model = er.normalize_spec({
            "entities": [{"name": name} for name in "ABC"],
            "relations": [{"a": "A", "b": "B"}, {"a": "B", "b": "C"}],
        })
        model.update(ent_w=[0.62] * 3, rel_w=[er.DW] * 2, attr_w=[[], []])
        topology = er.overview_topology(model)
        positions = {("e", 0): (-30, 0), ("e", 1): (0, 0), ("e", 2): (30, 0),
                     ("d", 0): (-15, 0), ("d", 1): (15, 0)}
        scene = er._planar_scene(model, positions, topology[1])
        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            # A tight search budget must preserve a readable connected result.
            result = er._verify_overview(model, scene, None, try_planar=True, render_deadline=0, topology=topology)
        self.assertNotIn("display_model", result)
        self.assertEqual(len(result["ents"]), 3)
        self.assertEqual(len(result["paths"]), 4)
        self.assertTrue(er._clear_planar_geometry(result))

    def test_axis_compaction_moves_tight_clusters_together(self):
        model = er.normalize_spec({
            'entities': [{'name': name} for name in 'ABCD'],
            'relations': [{'a': 'A', 'b': 'B'}, {'a': 'B', 'b': 'C'}, {'a': 'C', 'b': 'D'}],
        })
        model.update(ent_w=[0.62] * 4, rel_w=[0.86] * 3, attr_w=[[], [], []])
        _, connections = er.overview_topology(model)
        positions = {('e', 0): (-8, 0), ('e', 1): (-6.8, 0),
                     ('e', 2): (6.8, 0), ('e', 3): (8, 0),
                     ('d', 0): (-7.4, 1.5), ('d', 1): (0, 0), ('d', 2): (7.4, -1.5)}
        scene = er._planar_scene(model, positions, connections)
        mapping = er._axis_compaction_targets(scene, 0, 0.4, math.inf)
        compact = er._planar_scene(model, {node: mapping[point] for node, point in positions.items()}, connections)
        self.assertTrue(er._clear_planar_geometry(compact))
        self.assertLess(compact['ents'][3][0] - compact['ents'][0][0], 8)
        self.assertEqual([box[2:] for box in compact['boxes']], [box[2:] for box in scene['boxes']])
        self.assertEqual(len(compact['paths']), 6)
        self.assertTrue(all(len(path) == 2 for path in compact['paths']))
        self.assertEqual(scene['positions'], positions)

    def test_connected_fallback_retains_all_relations_and_original_entity_paths(self):
        import networkx as nx

        names = "ABCDEF"
        model = er.normalize_spec({
            "entities": [{"name": name} for name in names],
            "relations": [{"a": a, "b": b} for a in names[:3] for b in names[3:]],
        })
        model.update(ent_w=[0.62] * 6, attr_w=[[] for _ in range(9)])
        with patch.object(er, "tw", return_value=0.28), patch.object(er, "text_size", return_value=(0.09, 0.16)):
            scene = er._connected_overview_fallback(model, None, math.inf)
        self.assertIsNotNone(scene)
        visual = scene["display_model"]
        graph = nx.Graph()
        for index, relation in enumerate(visual["rels"]):
            self.assertEqual([(visual["ents"][i].get("reference_to", i), card) for i, card in relation["ends"]],
                             model["rels"][index]["ends"])
            graph.add_edges_from((('d', index), ('e', entity)) for entity, _ in relation["ends"])
        self.assertTrue(nx.is_connected(graph))
        self.assertEqual(len(scene["paths"]), 18)
        self.assertTrue(er._clear_planar_geometry(scene))
        self.assertEqual(er._cardinality_conflicts(scene["boxes"], scene["paths"], scene["labels"]), 0)

    def test_fallback_distributes_hub_branches_on_both_sides(self):
        model = er.normalize_spec({
            "entities": [{"name": name} for name in "ABCDEFGHIJK"],
            "relations": [{"a": "A", "b": name, "attrs": ["Note"]} for name in "BCDEFGHIJK"],
        })
        model.update(ent_w=[0.8] * 11, attr_w=[[0.8] for _ in range(10)])
        with patch.object(er, "tw", return_value=0.28), patch.object(er, "text_size", return_value=(0.09, 0.16)):
            scene = er._connected_overview_fallback(model, None, math.inf)
        self.assertIsNotNone(scene)
        self.assertEqual(len(scene["display_model"]["ents"]), 11)
        left, right, top, bottom = er._diagram_extents(scene["boxes"], scene["paths"], scene["labels"])
        self.assertGreater(right - left, bottom - top)
        hub_y = scene["ents"][0][1]
        self.assertTrue(any(box[1] < hub_y for box in scene["ents"][1:]))
        self.assertTrue(any(box[1] > hub_y for box in scene["ents"][1:]))
        self.assertTrue(er._clear_planar_geometry(scene))
        self.assertEqual(len(scene["paths"]), 30)

    def test_expired_final_compaction_preserves_verified_scene(self):
        model = er.normalize_spec({'entities': [{'name': 'A'}, {'name': 'B'}],
                                   'relations': [{'a': 'A', 'b': 'B'}]})
        model.update(ent_w=[0.62] * 2, rel_w=[0.86], attr_w=[[]])
        _, connections = er.overview_topology(model)
        scene = er._planar_scene(model, {('e', 0): (-3, 0), ('d', 0): (0, 0), ('e', 1): (3, 0)}, connections)
        with patch.object(er, 'text_size', return_value=(0.09, 0.16)):
            scene['labels'] = er.layout_cardinality_labels(model, scene, scene['paths'])
        self.assertIs(er._squeeze_verified_overview(model, scene, None, 0), scene)

    def test_clear_space_in_diamond_and_ellipse_corners_can_be_used(self):
        near_corner = (0.8, 0.8, 1.3, 0.8)
        through_center = (-1.3, 0, 1.3, 0)
        for kind in ("d", "a"):
            shape = (0, 0, 2, 2, kind, 0)
            self.assertFalse(er._line_hits_shape(near_corner, shape))
            self.assertTrue(er._line_hits_shape(through_center, shape))
        self.assertTrue(er._line_hits_shape(near_corner, (0, 0, 2, 2, "e", 0)))

    def test_candidate_collision_scoring_ignores_only_unchanged_pairs(self):
        boxes = [(0, 0, 1, 1, "e", 0), (0, 0.2, 1, 1, "e", 1),
                 (1, 0, 1, 1, "d", 0), (2, 0, 1, 1, "a", 0)]
        lines = [(-1, 0.2, 1, 0.2, 1, 1), (1, -1, 1, 1, 2, 0), (1, 0, 2, 0, 0, -1)]
        fixed = er.collisions(boxes[:2], lines[:2])
        self.assertGreater(fixed, 0)
        exact = er.collisions(boxes, lines, unchanged=(2, 2))
        self.assertEqual(exact, er.collisions(boxes, lines) - fixed)
        self.assertGreater(exact, 0)
        bounded = er.collisions(boxes, lines, unchanged=(2, 2), ceiling=1)
        self.assertGreaterEqual(bounded, 1)
        self.assertLessEqual(bounded, exact)
        self.assertEqual(er.collisions(boxes, lines, unchanged=(2, 2), ceiling=exact + 1), exact)

    def test_folds_empty_bands_without_crossing_or_resizing_shapes_and_labels(self):
        model = er.normalize_spec({
            "entities": [{"name": "A"}, {"name": "B"}],
            "relations": [{"name": "R", "a": "A", "b": "B"}],
        })
        model.update(ent_w=[0.62, 0.62], attr_w=[[]], rel_w=[er.DW])
        _, connections = er.overview_topology(model)
        positions = {("e", 0): (-12, -3), ("e", 1): (12, 3), ("d", 0): (0, 0)}
        scene = er._planar_scene(model, positions, connections)
        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            scene["labels"] = er.layout_cardinality_labels(model, scene, scene["paths"])

        folded = er._fold_empty_bands(scene, 0)

        self.assertLess(folded["ents"][1][0] - folded["ents"][0][0], 4)
        self.assertEqual([box[2:] for box in folded["boxes"]], [box[2:] for box in scene["boxes"]])
        self.assertEqual([label[2:] for label in folded["labels"]], [label[2:] for label in scene["labels"]])
        self.assertEqual(len(folded["paths"]), len(scene["paths"]))
        self.assertTrue(all(len(path) > 2 for path in folded["paths"]))
        self.assertTrue(er._clear_planar_geometry(folded))
        self.assertEqual(er._cardinality_conflicts(folded["boxes"], folded["paths"], folded["labels"]), 0)

    def test_compacts_clear_planar_geometry_without_losing_connections_or_labels(self):
        model = er.normalize_spec({
            "entities": [{"name": "A"}, {"name": "B"}],
            "relations": [{"name": "R", "a": "A", "b": "B", "attrs": ["Date"]}],
        })
        model.update(ent_w=[0.62, 0.62], attr_w=[[0.64]], rel_w=[er.DW])
        _, connections = er.overview_topology(model)
        positions = {("e", 0): (-8, 0), ("e", 1): (8, 0), ("d", 0): (0, 0), ("a", 0, 0): (0, 6)}
        scene = er._planar_scene(model, positions, connections)

        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            scene["labels"] = er.layout_cardinality_labels(model, scene, scene["paths"])
            compact = er._compact_planar_scene(model, scene, connections, None, math.inf)

        def area(candidate):
            x0, x1, y0, y1 = er._diagram_extents(candidate["boxes"], candidate["paths"], candidate["labels"])
            return (x1 - x0) * (y1 - y0)

        self.assertLess(area(compact), area(scene) / 2)
        self.assertTrue(er._clear_planar_geometry(compact))
        self.assertEqual(er._cardinality_conflicts(compact["boxes"], compact["paths"], compact["labels"]), 0)
        self.assertEqual(len(compact["paths"]), 3)
        self.assertEqual(len(compact["labels"]), 2)

    def test_compacts_an_outlying_self_relation_without_losing_either_end(self):
        model = er.normalize_spec({
            "entities": [{"name": name} for name in "ABC"],
            "relations": [{"name": "Link", "a": "A", "b": "B"},
                          {"name": "Reply", "a": "C", "b": "C"}],
        }, report_isolated=False)
        model.update(ent_w=[0.62] * 3, attr_w=[[], []], rel_w=[er.DW] * 2)
        embedding, connections = er.overview_topology(model)
        positions = {("e", 0): (0, 0), ("e", 1): (4, 0), ("d", 0): (2, 0),
                     ("e", 2): (17, 5), ("d", 1): (19, 5), ("bend", 1): (18, 6)}
        scene = er._planar_scene(model, positions, connections)
        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            scene["labels"] = er.layout_cardinality_labels(model, scene, scene["paths"])
            with patch.object(er, "_find_planar_seed", return_value=scene):
                compact = er._planar_candidate(model, embedding, connections, None, math.inf)

        self.assertLess(er._planar_readability(compact, None)[2], er._planar_readability(scene, None)[2] / 2)
        self.assertEqual(len(compact["paths"]), 4)
        self.assertEqual(len(compact["labels"]), 4)
        self.assertTrue(er._clear_planar_geometry(compact))
        self.assertEqual(er._cardinality_conflicts(compact["boxes"], compact["paths"], compact["labels"]), 0)

    def test_closes_large_local_gaps_without_adding_bends(self):
        model = er.normalize_spec({
            "entities": [{"name": name} for name in "ABC"],
            "relations": [{"name": "Left", "a": "A", "b": "B"},
                          {"name": "Right", "a": "B", "b": "C"}],
        })
        model.update(ent_w=[0.9] * 3, rel_w=[0.9] * 2, attr_w=[[], []])
        _, connections = er.overview_topology(model)
        positions = {("e", 0): (-8, 0), ("d", 0): (-6.8, 0), ("e", 1): (0, 0),
                     ("d", 1): (6.8, 0), ("e", 2): (8, 0)}
        scene = er._planar_scene(model, positions, connections)
        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            scene["labels"] = er.layout_cardinality_labels(model, scene, scene["paths"])
            compact = er._squeeze_verified_overview(model, scene, None, math.inf)

        self.assertLess(er._planar_readability(compact, None)[2], er._planar_readability(scene, None)[2] / 2)
        self.assertEqual([box[2:] for box in compact["boxes"]], [box[2:] for box in scene["boxes"]])
        self.assertEqual(len(compact["labels"]), 4)
        self.assertTrue(all(len(path) == 2 for path in compact["paths"]))
        self.assertTrue(er._clear_planar_geometry(compact))
        self.assertEqual(er._cardinality_conflicts(compact["boxes"], compact["paths"], compact["labels"]), 0)

    def test_grouped_overview_preserves_self_and_ternary_endpoints(self):
        model = er.normalize_spec({
            "entities": [{"name": name} for name in "ABCDE"],
            "relations": [{"name": "Join", "entities": ["A", "B", "C"],
                           "card": ["m", "n", "p"], "attrs": ["Date", "Note", "State"]},
                          {"name": "Reply", "a": "A", "b": "A"},
                          {"name": "Connect", "a": "C", "b": "D", "attrs": ["Note"]}],
        }, report_isolated=False)
        model.update(ent_w=[1.1] * 5, attr_w=[[0.9] * 3, [], [0.9]])
        with patch.object(er, "text_size", return_value=(0.28, 0.16)):
            scene = er._grouped_overview(model, None)
        self.assertIsNotNone(scene)
        display = scene["display_model"]
        for original, drawn in zip(model["rels"], display["rels"]):
            self.assertEqual(original["ends"], [
                (display["ents"][index].get("reference_to", index), card) for index, card in drawn["ends"]
            ])
        self.assertEqual(len(scene["ents"]), len(display["ents"]))
        self.assertEqual(len(scene["paths"]), 11)
        self.assertEqual(len(scene["labels"]), 7)
        self.assertTrue(er._clear_planar_geometry(scene))
        self.assertEqual(er._cardinality_conflicts(scene["boxes"], scene["paths"], scene["labels"]), 0)
        self.assertTrue(all(len(path) == 2 for path in scene["paths"]))

    def test_incremental_geometry_checks_moved_shape_against_unchanged_path(self):
        model = er.normalize_spec({
            "entities": [{"name": name} for name in "ABC"],
            "relations": [{"a": "A", "b": "B"}],
        })
        model.update(ent_w=[0.62] * 3, attr_w=[[]], rel_w=[er.DW])
        _, connections = er.overview_topology(model)
        points = {("e", 0): (-4, 0), ("e", 1): (4, 0), ("e", 2): (-2, 2), ("d", 0): (0, 0)}
        original = er._planar_scene(model, points, connections)
        moved = er._planar_scene(model, {**points, ("e", 2): (-2, 0)}, connections)

        self.assertTrue(er._clear_planar_geometry(original))
        self.assertEqual(moved["paths"], original["paths"])
        self.assertFalse(er._clear_planar_geometry(moved, previous=original))
        self.assertFalse(er._clear_planar_geometry(moved))

    def test_detects_rotatable_cycle_joined_at_one_entity(self):
        anchor = ("e", 0)
        first = (("e", 1), ("e", 2))
        second = (("e", 3), ("e", 4), ("e", 5))
        links = [(anchor, first[0]), (first[0], first[1]), (first[1], anchor),
                 (anchor, second[0]), (second[0], second[1]), (second[1], second[2]), (second[2], anchor)]

        bridges = er._bridge_branches([anchor, *first, *second], links)
        pivots = er._pivot_groups([anchor, *first, *second], links)

        self.assertEqual(bridges, [])
        self.assertEqual(pivots, [(anchor, first)])

    def test_packs_an_outlying_cycle_without_bending_or_crossing_its_edges(self):
        pairs = [(0, 1), (1, 2), (2, 0), (0, 3), (3, 4), (4, 5), (5, 0)]
        names = "ABCDEF"
        model = er.normalize_spec({"entities": [{"name": name} for name in names],
                                   "relations": [{"a": names[a], "b": names[b]} for a, b in pairs]})
        model.update(ent_w=[0.62] * 6, attr_w=[[] for _ in pairs], rel_w=[er.DW] * len(pairs))
        _, connections = er.overview_topology(model)
        points = [(0, 0), (-1, 12), (-3, 9), (6, -0.5), (8, -3), (4, -4)]
        positions = {("e", i): point for i, point in enumerate(points)}
        for i, (a, b) in enumerate(pairs):
            positions["d", i] = tuple((p + q) / 2 for p, q in zip(points[a], points[b]))
        original = er._planar_scene(model, positions, connections)
        self.assertTrue(er._clear_planar_geometry(original))
        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            original["labels"] = er.layout_cardinality_labels(model, original, original["paths"])
            packed = er._pack_pivot_groups(model, original, connections, None, math.inf)

        self.assertLess(er._planar_readability(packed, None)[5], 0.8 * er._planar_readability(original, None)[5])
        self.assertTrue(er._clear_planar_geometry(packed))
        self.assertEqual(len(packed["paths"]), len(original["paths"]))
        self.assertEqual(sum(map(er._path_bends, packed["paths"])), 0)
        self.assertEqual(er._cardinality_conflicts(packed["boxes"], packed["paths"], packed["labels"]), 0)

    def test_planar_fallback_rebuilds_a_crossed_layout_without_dropping_links(self):
        model = er.normalize_spec({
            "entities": [{"name": name} for name in "ABCD"],
            "relations": [{"a": "A", "b": "B", "attrs": ["Date"]}, {"a": "C", "b": "D"}],
        })
        model.update(ent_w=[0.62] * 4, attr_w=[[0.64], []])
        crossed = er.compose(model, [(0, 0), (4, 3), (0, 3), (3, 0)])
        crossed["paths"] = er.route_overview(crossed, optimize=False)
        self.assertGreater(er.overview_quality(crossed, crossed["paths"])[2], 0)

        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            chosen = er._verify_overview(model, crossed, None, try_planar=True)

        self.assertEqual(chosen["quality"], {"planar": True, "overlaps": 0, "boxHits": 0,
                                             "lineConflicts": 0, "labelConflicts": 0})
        self.assertEqual(len(chosen["paths"]), 5)
        self.assertEqual(len(chosen["labels"]), 4)
        self.assertEqual(len(chosen["attrs"]), 1)

    def test_planar_search_prefers_a_later_more_readable_candidate(self):
        model = er.normalize_spec({
            "entities": [{"name": name} for name in "ABCDEF"],
            "relations": [{"name": "R", "a": "A", "b": "B"}],
        })
        model.update(ent_w=[0.62] * 6, attr_w=[[]], rel_w=[er.DW])
        embedding, connections = er.overview_topology(model)

        def scene_at(width):
            points = [(-width, 0), (width, 0), (-width, 1), (width, 1), (-width, -1), (width, -1)]
            positions = {("e", i): point for i, point in enumerate(points)}
            positions["d", 0] = (0, 0)
            scene = er._planar_scene(model, positions, connections)
            return dict(scene, labels=er.layout_cardinality_labels(model, scene, scene["paths"]))

        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            wide, compact = scene_at(8), scene_at(2)
            with patch.object(er, "_find_planar_seed", side_effect=[wide, compact]), patch.object(
                er, "_alternate_embeddings", return_value=[embedding]
            ), patch.object(
                er, "_compact_planar_scene", side_effect=lambda _model, scene, *_: scene
            ):
                chosen = er._planar_candidate(model, embedding, connections, None, math.inf)

        self.assertIs(chosen, compact)
        self.assertTrue(er._clear_planar_geometry(chosen))
        self.assertEqual(er._cardinality_conflicts(chosen["boxes"], chosen["paths"], chosen["labels"]), 0)

    def test_nonplanar_topology_uses_a_visual_reference_and_keeps_every_link(self):
        names = "ABCDEF"
        model = er.normalize_spec({
            "entities": [{"name": name} for name in names],
            "relations": [{"a": a, "b": b} for a in names[:3] for b in names[3:]],
        })
        model.update(ent_w=[0.62] * 6, attr_w=[[] for _ in range(9)])
        positions = [(0, 0), (0, 2), (0, 4), (5, 0), (5, 2), (5, 4)]
        scene = er.compose(model, positions)

        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            chosen = er._verify_overview(model, scene, None, try_planar=True)

        self.assertTrue(chosen["quality"]["planar"])
        self.assertEqual(len(chosen["paths"]), 18)
        self.assertEqual(len(chosen["labels"]), 18)
        self.assertEqual(chosen["quality"]["lineConflicts"], 0)
        self.assertEqual(len(chosen["display_model"]["ents"]), len(names) + 1)
        self.assertEqual(len(model["ents"]), len(names))
        visual = chosen["display_model"]
        for original, displayed in zip(model["rels"], visual["rels"]):
            self.assertEqual(original["ends"], [(visual["ents"][i].get("reference_to", i), card)
                                                for i, card in displayed["ends"]])

    def test_selects_candidate_using_the_paths_that_will_be_drawn(self):
        model = er.normalize_spec({
            "entities": [{"name": name} for name in "ABCD"],
            "relations": [{"a": "A", "b": "B"}, {"a": "C", "b": "D"}],
        })
        model.update(ent_w=[0.62] * 4, attr_w=[[], []])
        crossed = er.compose(model, [(0, 0), (4, 3), (0, 3), (3, 0)])
        clear = er.compose(model, [(0, 0), (4, 3), (0, 3), (2, 3)])
        straight = er.route_overview(crossed, optimize=False)
        clear_paths = er.route_overview(clear, optimize=False)

        with patch.object(er, "route_overview", side_effect=[straight, clear_paths]) as route:
            chosen = er.choose_overview_scene([crossed, clear])

        self.assertEqual(route.call_count, 2)
        self.assertEqual(chosen["P"], clear["P"])
        self.assertIs(chosen["paths"], clear_paths)

    def test_overview_reroutes_crossing_without_moving_entities(self):
        model = er.normalize_spec({
            "entities": [{"name": name} for name in "ABCD"],
            "relations": [{"a": "A", "b": "B"}, {"a": "C", "b": "D"}],
        })
        model.update(ent_w=[0.62] * 4, attr_w=[[], []])
        positions = [(0, 0), (4, 3), (0, 3), (3, 0)]
        scene = er.compose(model, positions)

        def count_crossings(paths):
            segments = [er._path_segments(path) for path in paths]
            return sum(er._path_crosses(a, b) for i, path in enumerate(segments)
                       for earlier in segments[:i] for a in path for b in earlier)

        straight = er.route_overview(scene, optimize=False)
        routed = er.route_overview(scene)
        self.assertEqual(count_crossings(straight), 1)
        self.assertEqual(count_crossings(routed), 0)
        self.assertEqual([entity[:2] for entity in scene["ents"]], positions)
        self.assertTrue(any(len(path) > 2 for path in routed))

    def test_visibility_search_can_detour_around_an_unrelated_shape(self):
        source = (0, 0, 0.8, 0.6, "d", 0)
        target = (6, 0, 0.8, 0.6, "e", 0)
        blocker = (3, 0, 2.0, 1.2, "e", 1)
        boxes = [source, target, blocker]
        path = er._visibility_detour(source[:2], target[:2], source, target, boxes, [], math.inf)

        self.assertIsNotNone(path)
        self.assertGreaterEqual(len(path), 4)
        self.assertEqual(er._route_box_hits(er._path_segments(path), boxes, source, target), 0)

    def test_straightens_an_unnecessary_bend_without_touching_entities(self):
        model = er.normalize_spec({
            "entities": [{"name": "A"}, {"name": "B"}],
            "relations": [{"a": "A", "b": "B"}],
        })
        model.update(ent_w=[0.62, 0.62], attr_w=[[]])
        scene = er.compose(model, [(-2, 0), (2, 0)])
        _, edges = er._overview_edges(scene)
        start, end, source, target, _ = edges[0]
        paths = er.route_overview(scene, optimize=False)
        paths[0] = er._visible_path((start, (-1, 0.8), end), source, target)
        quality = {"planar": True, "overlaps": 0, "boxHits": 0, "lineConflicts": 0, "labelConflicts": 0}

        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            labels = er.layout_cardinality_labels(model, scene, paths)
            result = er._straighten_overview(model, dict(scene, paths=paths, labels=labels), None, quality, math.inf)

        self.assertEqual(result["ents"], scene["ents"])
        self.assertEqual(result["quality"], quality)
        self.assertEqual(sum(map(er._path_bends, result["paths"])), 0)

    def test_moves_an_endpoint_to_replace_a_blocked_detour_with_a_straight_line(self):
        model = er.normalize_spec({
            "entities": [{"name": name} for name in ("A", "B", "Blocker")],
            "relations": [{"a": "A", "b": "B", "card": "1:n"}],
        }, report_isolated=False)
        model.update(ent_w=[0.62] * 3, rel_w=[0.8], attr_w=[[]])
        _, connections = er.overview_topology(model)
        scene = er._planar_scene(model, {("e", 0): (-2, 0), ("e", 1): (4, 0),
                                        ("e", 2): (2, 0.05), ("d", 0): (0, 0)}, connections)
        boxes, edges = er._overview_edges(scene)
        index = next(i for i, edge in enumerate(edges) if edge[3][5] == 1)
        start, end, source, target, _ = edges[index]
        direct = scene["paths"][index]
        self.assertGreater(er._route_box_hits(er._path_segments(direct), boxes, source, target, exact=True), 0)
        scene["paths"][index] = er._visible_path((start, (1, -0.8), (3, -0.8), end), source, target)
        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            scene["labels"] = er.layout_cardinality_labels(model, scene, scene["paths"])
            self.assertTrue(er._clear_planar_geometry(scene))
            compact = er._squeeze_verified_overview(model, scene, None, math.inf)

        self.assertEqual(sum(map(er._path_bends, compact["paths"])), 0)
        self.assertTrue(er._clear_planar_geometry(compact))
        self.assertEqual(er._cardinality_conflicts(compact["boxes"], compact["paths"], compact["labels"]), 0)
        self.assertEqual([seg[4:] for seg in compact["segs"]], [seg[4:] for seg in scene["segs"]])

    def test_expired_search_budget_keeps_a_candidate_without_more_iterations(self):
        with patch.object(er, "quick_cost", return_value=10) as score:
            cost, candidate = er.anneal({"ents": [None, None]}, 2, 2, 1, 1, 0, 900, deadline=0)

        self.assertEqual(cost, 10)
        self.assertEqual(len(set(candidate)), 2)
        score.assert_called_once()

    def test_manual_layout_reuses_positions_for_both_export_formats(self):
        spec = {
            "entities": [{"name": "Reader"}, {"name": "Book"}],
            "relations": [{"name": "Borrows", "a": "Reader", "b": "Book"}],
            "positions": {"Book": [2, 1], "Reader": [0, 0]},
            "relationPositions": [[1, -0.75]],
        }
        font = Path(er.matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
        with patch.object(er, "find_font", return_value=str(font)), patch.object(
            er, "layout_er", side_effect=AssertionError("manual layout must bypass automatic layout")
        ):
            png = render_in_worker({"spec": spec, "format": "png"})
            svg = render_in_worker({"spec": spec, "format": "svg"})
            overlap = {**spec, "positions": {"Book": [0, 0], "Reader": [0, 0]}}
            rejected = render_in_worker({"spec": overlap, "format": "png"})

        self.assertEqual(png["layout"], svg["layout"])
        self.assertEqual([(item["entity"], item["x"], item["y"]) for item in png["layout"]["entities"]],
                         [("Reader", 0, 0), ("Book", 2, 1)])
        self.assertEqual([(item["index"], item["x"], item["y"]) for item in png["layout"]["relations"]],
                         [(0, 1, -0.75)])
        self.assertTrue(all(value == 0 for key, value in png["layout"]["quality"].items() if key != "planar"))
        self.assertTrue(png["overview"]["url"].startswith("data:image/png;base64,"))
        self.assertTrue(svg["overview"]["url"].startswith("data:image/svg+xml;base64,"))
        self.assertIn("重叠", rejected["error"])

    def test_rejects_mismatched_and_invalid_layout_coordinates(self):
        spec = {"entities": [{"name": "Reader"}]}
        for positions in ({}, {"Other": [0, 0]}, {"Reader": [False, 1]}, {"Reader": [float("nan"), 0]}):
            with self.subTest(positions=positions):
                result = render_in_worker({"spec": {**spec, "positions": positions}, "format": "png"})
                self.assertIn("error", result)

    def test_entity_lines_end_at_shapes_and_have_equal_visible_lengths(self):
        attrs = [("岗位类别ID", True), ("类别描述", False), ("类别名称", False)]
        with patch.object(er, "tw", side_effect=lambda text: len(text) * 0.14):
            layout = er.layout_entity("岗位类别", attrs)

        lengths = []
        for line, (cx, cy), (w, h) in zip(layout["lines"], layout["pos"], layout["sizes"]):
            x0, y0, x1, y1 = line
            self.assertAlmostEqual(max(abs(x0) / (layout["rw"] / 2), abs(y0) / (layout["rh"] / 2)), 1)
            self.assertAlmostEqual(((x1 - cx) / (w / 2)) ** 2 + ((y1 - cy) / (h / 2)) ** 2, 1)
            lengths.append(math.hypot(x1 - x0, y1 - y0))
        self.assertEqual(len(lengths), len(attrs))
        self.assertGreater(min(lengths), 0)
        self.assertAlmostEqual(max(lengths), min(lengths))

    def test_cardinality_labels_clear_shapes_lines_and_each_other(self):
        model = er.normalize_spec({
            "entities": [{"name": "技能"}, {"name": "岗位"}, {"name": "学习任务"}],
            "relations": [
                {"name": "前置", "a": "技能", "b": "技能", "card": ["m", "n"]},
                {"name": "要求", "a": "岗位", "b": "技能", "card": ["m", "n"], "attrs": ["要求等级"]},
                {"name": "对应", "a": "技能", "b": "学习任务", "card": ["1", "n"]},
            ],
        })
        model.update(ent_w=[0.62, 0.62, 0.94], attr_w=[[], [0.82], []])
        scene = er.compose(model, [(0, 0), (0, -1.55), (1.75, 0.45)])
        with patch.object(er, "text_size", return_value=(0.09, 0.16)):
            labels = er.layout_cardinality_labels(model, scene)

        self.assertCountEqual([label[4] for label in labels], ["m", "n", "m", "n", "1", "n"])
        for i, label in enumerate(labels):
            self.assertFalse(any(er.label_hits_shape(label, shape) for shape in scene["boxes"]))
            self.assertFalse(any(er._seg_hits_rect(*seg[:4], *label[:4]) for seg in scene["segs"]))
            self.assertFalse(any(er.boxes_overlap(label, other) for other in labels[:i]))
