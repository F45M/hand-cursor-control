import math
from types import SimpleNamespace
import unittest
from gestures import Hand, GestureEngine, CursorFilter, Settings


def hand(distances=(1.4, 1.6, 1.5, 1.2), cursor=(0.5, 0.5),
         scroll_pose=False, scroll_y=0.5, open_palm=True):
    return Hand(cursor, distances, scroll_pose, scroll_y, open_palm)


def scrolling(y=0.5, distances=(1.4, 1.6, 1.5, 1.2)):
    return hand(distances, scroll_pose=True, scroll_y=y, open_palm=False)


class GesturesTest(unittest.TestCase):
    def setUp(self):
        self.engine = GestureEngine()
        self.engine.update(hand(), 0)
        self.engine.update(hand(), 0.2)

    def pinch(self, index):
        d = [1.4, 1.6, 1.5, 1.2]
        d[index] = 0.12
        return hand(tuple(d))

    def enter_scroll(self):
        self.assertEqual(self.engine.update(scrolling(), 0.3), [])
        self.assertEqual(self.engine.update(scrolling(), 0.4), [])
        self.assertEqual(self.engine.update(scrolling(), 0.54), [])
        self.assertTrue(self.engine.scrolling)

    def test_each_short_pinch_clicks_once_on_release(self):
        for index, button in enumerate(('left', 'right', 'middle')):
            with self.subTest(button=button):
                self.setUp()
                self.assertEqual(self.engine.update(self.pinch(index), 0.3), [])
                self.assertEqual(self.engine.update(self.pinch(index), 0.4), [])
                self.assertEqual(self.engine.update(hand(), 0.5), [('click', button)])
                self.assertEqual(self.engine.update(hand(), 0.6), [])

    def test_hold_and_release_each_button(self):
        for index, button in enumerate(('left', 'right', 'middle')):
            with self.subTest(button=button):
                self.setUp()
                self.engine.update(self.pinch(index), 0.3)
                self.assertTrue(self.engine.freeze_cursor)
                self.assertEqual(self.engine.update(self.pinch(index), 0.75), [('down', button)])
                self.assertFalse(self.engine.freeze_cursor)
                self.assertEqual(self.engine.update(self.pinch(index), 1), [])
                self.assertEqual(self.engine.update(hand(), 1.1), [('up', button)])

    def test_loss_releases_drag_and_requires_open_hand(self):
        self.engine.update(self.pinch(0), 0.3)
        self.engine.update(self.pinch(0), 0.8)
        self.assertEqual(self.engine.update(None, 0.9), [('up', 'left')])
        for t in (1, 1.5, 2):
            self.assertEqual(self.engine.update(self.pinch(0), t), [])
        self.assertFalse(self.engine.armed)

    def test_lost_short_pinch_is_cancelled(self):
        self.engine.update(self.pinch(1), 0.3)
        self.assertEqual(self.engine.update(None, 0.4), [])

    def test_starting_with_pinch_never_clicks(self):
        engine = GestureEngine()
        for t in (0, 0.2, 0.8, 1.2):
            self.assertEqual(engine.update(self.pinch(0), t), [])
        self.assertEqual(engine.update(hand(), 1.3), [])

    def test_contact_jitter_does_not_release_drag(self):
        self.engine.update(self.pinch(0), 0.3)
        self.engine.update(self.pinch(0), 0.8)
        self.assertEqual(self.engine.update(hand((0.32, 1.6, 1.5, 1.2)), 0.9), [])
        self.assertTrue(self.engine.held)

    def test_very_short_noise_does_not_click(self):
        self.engine.update(self.pinch(0), 0.3)
        self.assertEqual(self.engine.update(hand(), 0.33), [])

    def test_multiple_contacts_and_partial_release_do_not_click(self):
        self.engine.update(hand((0.1, 0.1, 1.5, 1.2)), 0.3)
        for t in (0.4, 0.9):
            self.assertEqual(self.engine.update(self.pinch(0), t), [])
        self.assertEqual(self.engine.update(hand(), 1), [])

    def test_five_finger_gather_no_longer_scrolls(self):
        for t, d in ((0.3, 0.9), (0.4, 0.5), (0.5, 0.1), (0.6, 0.6), (0.7, 1.2)):
            self.assertEqual(self.engine.update(hand((d, d, d, d)), t), [])
        self.assertFalse(self.engine.scrolling)

    def test_reset_releases_only_once(self):
        self.engine.update(self.pinch(2), 0.3)
        self.engine.update(self.pinch(2), 0.8)
        self.assertEqual(self.engine.reset(), [('up', 'middle')])
        self.assertEqual(self.engine.reset(), [])

    def test_scroll_requires_stable_pose_and_anchors_after_entry(self):
        self.engine.update(scrolling(0.3), 0.3)
        self.assertTrue(self.engine.freeze_cursor)
        self.assertFalse(self.engine.scrolling)
        self.assertEqual(self.engine.update(scrolling(0.6), 0.54), [])
        self.assertTrue(self.engine.scrolling)
        for i in range(10):
            self.assertEqual(self.engine.update(scrolling(0.6), 0.6+i*0.03), [])

    def test_scroll_up_and_down_at_different_frame_rates(self):
        for fps in (15, 30, 60):
            for direction in (-1, 1):
                with self.subTest(fps=fps, direction=direction):
                    self.setUp()
                    self.enter_scroll()
                    events = []
                    for i in range(1, fps+1):
                        events += self.engine.update(scrolling(0.5 + direction*0.2*i/fps), 0.54+i/fps)
                    self.assertTrue(events)
                    self.assertTrue(all(a == 'scroll' and v*direction < 0 for a, v in events))
                    self.assertTrue(4 <= sum(abs(v) for _, v in events) <= 6)
                    self.assertTrue(self.engine.freeze_cursor)

    def test_stationary_jitter_never_scrolls(self):
        self.enter_scroll()
        for i in range(100):
            self.assertEqual(self.engine.update(scrolling(0.5 + 0.006*math.sin(i)), 0.57+i/30), [])

    def test_open_hand_movement_does_not_scroll(self):
        for i in range(20):
            self.assertEqual(self.engine.update(hand(scroll_y=i/20), 0.3+i/30), [])

    def test_every_pinch_has_priority_over_scroll_pose(self):
        for index, button in enumerate(('left', 'right', 'middle')):
            with self.subTest(button=button):
                self.setUp()
                pinch = self.pinch(index)
                pinch.scroll_pose = True
                self.engine.update(pinch, 0.3)
                self.assertEqual(self.engine.update(pinch, 0.75), [('down', button)])
                self.assertFalse(self.engine.scrolling)
                self.assertEqual(self.engine.update(scrolling(), 0.8), [('up', button)])

    def test_middle_click_from_two_finger_candidate_is_not_swallowed(self):
        self.engine.update(scrolling(), 0.3)
        pinch = self.pinch(2)
        pinch.scroll_pose = True
        self.engine.update(pinch, 0.4)
        self.assertEqual(self.engine.update(scrolling(), 0.55), [('click', 'middle')])

    def test_scroll_blocks_every_pinch_and_needs_neutral_before_clicking(self):
        for index in range(3):
            with self.subTest(index=index):
                self.setUp()
                self.enter_scroll()
                for t in (0.6, 0.8, 1, 1.5):
                    self.assertEqual(self.engine.update(self.pinch(index), t), [])
                self.assertFalse(self.engine.armed)
                self.engine.update(hand(), 1.6)
                self.engine.update(hand(), 1.8)
                self.assertTrue(self.engine.armed)
                self.engine.update(self.pinch(index), 1.9)
                self.assertEqual(self.engine.update(hand(), 2.1), [('click', self.engine.BUTTONS[index])])

    def test_pose_dropout_stops_scroll_and_rebases_on_recovery(self):
        self.enter_scroll()
        self.assertEqual(self.engine.update(hand(scroll_y=0.7), 0.6), [])
        self.assertEqual(self.engine.update(scrolling(0.7), 0.66), [])
        self.assertTrue(self.engine.scrolling)
        self.assertEqual(self.engine.update(scrolling(0.7), 0.72), [])

    def test_tracking_loss_cancels_scroll(self):
        self.enter_scroll()
        self.assertEqual(self.engine.update(None, 0.6), [])
        self.assertFalse(self.engine.scrolling)
        for t in (0.7, 0.9, 1.2):
            self.assertEqual(self.engine.update(scrolling(0.2), t), [])
        self.assertFalse(self.engine.armed)

    def test_large_position_jump_and_stale_frame_do_not_scroll(self):
        self.enter_scroll()
        self.assertEqual(self.engine.update(scrolling(0.9), 0.6), [])
        self.assertEqual(self.engine.update(scrolling(0.8), 1.2), [])
        self.assertEqual(self.engine.update(scrolling(0.8), 1.26), [])

    def test_cursor_reaches_edges_and_smooths_motion(self):
        cfg = Settings()
        filt = CursorFilter()
        self.assertEqual(filt.update((0, 0), 0, cfg), (0, 0))
        x, y = filt.update((1, 1), 0.03, cfg)
        self.assertTrue(0 < x < 1)
        self.assertEqual(x, y)
        for i in range(1, 101):
            p = filt.update((1, 1), i/20, cfg)
        self.assertAlmostEqual(p[0], 1)


class LandmarkGeometryTest(unittest.TestCase):
    def landmarks(self, folded=(False, False, True, True), mirrored=False):
        points = [SimpleNamespace(x=0.5, y=0.8) for _ in range(21)]
        for x, base, fold in zip((0.35, 0.45, 0.55, 0.65), (5, 9, 13, 17), folded):
            coordinates = ((x, 0.6), (x, 0.48), (x, 0.36), (x, 0.24))
            if fold:
                coordinates = ((x, 0.6), (x, 0.48), (x, 0.57), (x, 0.66))
            for index, (px, py) in enumerate(coordinates, base):
                points[index] = SimpleNamespace(x=px, y=py)
        points[4] = SimpleNamespace(x=0.15, y=0.6)
        if mirrored:
            for p in points:
                p.x = 1-p.x
        return points

    def test_two_fingers_recognized_for_either_hand_and_scaled_frame(self):
        for mirror in (False, True):
            points = self.landmarks(mirrored=mirror)
            a = Hand.from_landmarks(points, 640, 480)
            b = Hand.from_landmarks(points, 1280, 960)
            self.assertEqual(a, b)
            self.assertTrue(a.scroll_pose)
            self.assertFalse(a.open_palm)
            self.assertEqual(a.cursor, (points[8].x, points[8].y))

    def test_open_hand_and_one_finger_are_not_scroll_pose(self):
        opened = Hand.from_landmarks(self.landmarks((False,)*4), 640, 480)
        one = Hand.from_landmarks(self.landmarks((False, True, True, True)), 640, 480)
        self.assertTrue(opened.open_palm)
        self.assertFalse(opened.scroll_pose)
        self.assertFalse(one.scroll_pose)


if __name__ == '__main__':
    unittest.main()
