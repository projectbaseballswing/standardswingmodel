import copy
import json
import unittest

import numpy as np

from feedback.pose3d_display.preprocess import frozen, package, preprocess


def fixture(n=60):
    p = [[-.2,.55,0],[.2,.55,0],[-.35,.3,0],[.35,.3,0],[-.4,.1,0],[.4,.1,0],
         [-.13,0,0],[.13,0,0],[-.13,-.45,0],[.13,-.45,0],[-.13,-.85,0],[.13,-.85,0]]
    return {'schema_version': 1, 'id': 'unseen-input', 'title': 'Synthetic',
        'coordinate_convention': frozen.CONFIG['coordinate_contract'],
        'source_oriented': True, 'mirrored_input': False, 'handedness': 'unknown',
        'joint_names': frozen.BODY_NAMES, 'frame_count': n, 'fps': 60.,
        'foot_joint_names': ['left_heel','right_heel','left_foot_index','right_foot_index'],
        'source_provenance': {'source_sha256': 'a' * 64},
        'frames': [{'index': i, 'timestamp_s': i / 60, 'decoded_pts_s': i / 60,
                    'positions': copy.deepcopy(p),
                    'p2': {'edge_visible': [True]*12, 'torso_visible': True,
                           'joint_warnings': [False]*12, 'warnings': []}}
                   for i in range(n)]}


class IntegrationPreprocessTests(unittest.TestCase):
    def test_actual_pts_and_nominal_timestamp_are_distinct(self):
        c = fixture(20)
        for i, f in enumerate(c['frames']):
            f['decoded_pts_s'] = 4. + i/30.
        original = copy.deepcopy(c)
        raw, display = preprocess(c)
        self.assertEqual(c, original)
        np.testing.assert_allclose([f['timestamp_s'] for f in raw['frames']], np.arange(20)/30, atol=1e-15)
        self.assertEqual(display['frames'][19]['npz_timestamp_s'], 19/60)
        self.assertEqual(display['fps'], 60.)

    def test_no_double_smoothing(self):
        _, display = preprocess(fixture())
        with self.assertRaisesRegex(ValueError, 'repeated smoothing'):
            preprocess(display)

    def test_corrupt_coordinate_or_timestamp_contract_rejected(self):
        for mutation in ('mirror', 'coordinate', 'time', 'frame', 'policy'):
            c = fixture()
            if mutation == 'mirror': c['source_oriented'] = False
            if mutation == 'coordinate': c['coordinate_convention'] = 'image_pixels'
            if mutation == 'time': c['frames'][5]['decoded_pts_s'] = 0.
            if mutation == 'frame': c['frames'][5]['index'] = 3
            if mutation == 'policy': c['frames'][5]['p2']['edge_visible'] = []
            with self.assertRaises(ValueError): preprocess(c)

    def test_preserve_missing_and_p2_states_and_input(self):
        c = fixture()
        c['frames'][20]['positions'][4] = None
        c['frames'][30]['positions'] = [None]*12
        c['frames'][10]['p2']['edge_visible'][2] = False
        c['frames'][10]['p2']['joint_warnings'][4] = True
        before = copy.deepcopy(c)
        _, output = preprocess(c)
        self.assertEqual(c, before)
        self.assertTrue(all('feet' not in f for f in output['frames']))
        for a, b in zip(c['frames'], output['frames']):
            self.assertEqual(a['p2'], b['p2'])
            self.assertEqual([x is None for x in a['positions']], [x is None for x in b['positions']])

    def test_no_crossing_missing_or_large_time_gap(self):
        times = np.arange(60)/60
        points = np.zeros((60, 1, 3)); points[25] = np.nan; points[26:] = 10.
        result, _ = frozen.robust_local_polynomial(points, times, 1., .12)
        np.testing.assert_allclose(result, points, atol=1e-12, equal_nan=True)
        times[30:] += 1.
        points[30:] = 20.
        result, _ = frozen.robust_local_polynomial(points, times, 1., .12)
        np.testing.assert_allclose(result, points, atol=1e-12, equal_nan=True)

    def test_irregular_timestamp_quadratic_is_preserved(self):
        times = np.r_[0., np.cumsum(np.tile([.013,.019,.015,.018], 20))]
        points = np.stack([.1*times*times, .2*times, np.full_like(times,.3)], -1)[:,None,:]
        result, _ = frozen.robust_local_polynomial(points, times, 1., .12)
        np.testing.assert_allclose(result, points, atol=1e-12)

    def test_known_fast_motion_peak_not_excessively_blunted(self):
        times = np.arange(120)/120
        points = np.zeros((120,1,3)); points[:,0,0] = .3*np.tanh((times-.5)/.035)
        output, _ = frozen.robust_local_polynomial(points, times, 1., .12)
        raw_speed = frozen.adjacent_speed(points, times, .12)[:,0]
        new_speed = frozen.adjacent_speed(output, times, .12)[:,0]
        self.assertGreater(new_speed.max()/raw_speed.max(), .8)
        self.assertLessEqual(abs(np.argmax(new_speed)-np.argmax(raw_speed)), 1)

    def test_left_right_reflection_and_renaming_have_no_special_cases(self):
        c = fixture()
        rng = np.random.default_rng(9)
        for f in c['frames']:
            p = np.asarray(f['positions']); p += rng.normal(0,.004,p.shape)
            p -= (p[6]+p[7])[None,:]*.5; f['positions'] = p.tolist()
        reflection = copy.deepcopy(c)
        reflection.update(id='different-person', title='different-title', handedness='left', mirrored_input=True)
        swap = [1,0,3,2,5,4,7,6,9,8,11,10]
        for f in reflection['frames']:
            p = np.asarray(f['positions'])[swap]; p[:,0] *= -1; f['positions'] = p.tolist()
        _, a = preprocess(c); _, b = preprocess(reflection)
        for fa, fb in zip(a['frames'], b['frames']):
            expected = np.asarray(fa['positions'])[swap]; expected[:,0] *= -1
            np.testing.assert_allclose(expected, fb['positions'], atol=1e-12)

    def test_ankle_constraint_carries_available_feet_without_changing_direction(self):
        c = fixture()
        for f in c['frames']:
            f['feet'] = [[-.13,-.87,-.05],[.13,-.87,-.05],[-.13,-.87,.18],[.13,-.87,.18]]
        _, body, feet = frozen.clip_arrays(c)
        scale, refs, meta = frozen.scale_and_references(body, c)
        body[10,10,1] -= .15
        output, output_feet, _ = frozen.length_constraints(body, feet, c, scale, refs, meta['reference_eligible_counts'])
        shift = output[10,10]-body[10,10]
        self.assertGreater(np.linalg.norm(shift), 0.)
        self.assertLessEqual(np.linalg.norm(shift), .015*scale+1e-14)
        np.testing.assert_allclose(output_feet[10,0]-feet[10,0], shift, atol=1e-14)
        np.testing.assert_allclose(output_feet[10,2]-output_feet[10,0], feet[10,2]-feet[10,0], atol=1e-14)

    def test_contract_is_strict_json_and_frame_count_independent(self):
        for n in (1, 7, 42):
            bundle = package(fixture(n), 'unseen-input')
            json.dumps(bundle, allow_nan=False)
            self.assertEqual(len(bundle['display_orientation']['frames']), n)
            self.assertEqual(bundle['processing']['smoothing_passes'], 1)
            self.assertFalse(bundle['processing']['interpolation'])

    def test_foot_order_is_not_guessed(self):
        c = fixture()
        for f in c['frames']:
            f['feet'] = [None]*4
        c['foot_joint_names'] = ['right_heel','left_heel','left_foot_index','right_foot_index']
        with self.assertRaisesRegex(ValueError, 'heel/toe order'):
            preprocess(c)

    def test_pre_normalized_raw_gets_explicit_truthful_s0_contract(self):
        c = fixture()
        c['temporal_adapter'] = {'source': 'decoded_pts_s', 'origin_s': 0.}
        packed = package(c, 'unseen-input')
        self.assertEqual(packed['raw_orientation']['smoothing']['condition'], 'S0')
        self.assertFalse(packed['raw_orientation']['smoothing']['joint_coordinates_modified'])
        self.assertEqual([f['positions'] for f in packed['raw_orientation']['frames']],
                         [f['positions'] for f in c['frames']])


if __name__ == '__main__':
    unittest.main()
