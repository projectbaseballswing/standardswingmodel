"""Same-call capture, raw preservation and strict display contract tests.

The fake landmarker is explicitly a unit fixture, not real-video E2E evidence.
"""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from feedback.pipeline import SkeletonResult
from feedback.pose3d import (
    BODY_INDICES, FOOT_INDICES, P2_SHA, Pose3DCapture, Pose3DError,
    build_pose3d, restore_world,
)


WORLD = np.asarray([
    [-.20,-.55,0], [.20,-.55,0], [-.34,-.32,.04], [.34,-.32,.04],
    [-.40,-.13,.10], [.40,-.13,.10], [-.14,0,0], [.14,0,0],
    [-.16,.40,.03], [.16,.40,.03], [-.18,.80,0], [.18,.80,0],
])


def observed_result(index=0):
    image = [SimpleNamespace(x=.5,y=.5,z=.02,visibility=.95,presence=.98) for _ in range(33)]
    world = [SimpleNamespace(x=0.,y=0.,z=0.) for _ in range(33)]
    for j,k in enumerate(BODY_INDICES):
        x,y,z=WORLD[j]
        image[k]=SimpleNamespace(x=.5+x*.6+index*.0002,y=.2+(y+.55)*.5,z=.02,
                                 visibility=.95,presence=.98)
        world[k]=SimpleNamespace(x=x+index*.0003,y=y,z=z)
    for j,k in enumerate(FOOT_INDICES):
        x = -.18 if j%2==0 else .18
        world[k]=SimpleNamespace(x=x,y=.81,z=-.03 if j<2 else .12)
        image[k]=SimpleNamespace(x=.5+x*.6,y=.88,z=.03,visibility=.95,presence=.98)
    return SimpleNamespace(pose_landmarks=[image],pose_world_landmarks=[world])


class FakeLandmarker:
    def __init__(self):self.times=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def detect_for_video(self,image,time):
        self.times.append(time)
        return observed_result(len(self.times)-1)


def capture_data(count=9, mirrored=False):
    world=np.repeat(WORLD[None],count,axis=0)
    feet=np.repeat(np.asarray([[-.18,.81,-.03],[.18,.81,-.03],[-.18,.81,.12],[.18,.81,.12]])[None],count,axis=0)
    return {'world_raw':world,'foot_world_raw':feet,'visibility_raw':np.ones((count,12))*.95,
        'foot_visibility_raw':np.ones((count,4))*.95,'image_pixel_raw':np.zeros((count,12,3)),
        'image_quality':{k:np.zeros((count,12),bool) for k in ['combined_missing','interpolated','edge_filled']},
        'decoded_pts_s':np.arange(count)/60+.1,'fps':60.,'width':1920,'height':1080,
        'mirrored_input':mirrored,'handedness':'left' if mirrored else 'right'}


def skeleton(data=None):
    data=capture_data() if data is None else data
    count=len(data['decoded_pts_s'])
    return SkeletonResult(np.ones((count,12,3)),np.ones((count,12,3))*20,
        np.ones((count,12)),60.,(1920,1080),0,pose3d_capture=data)


class Pose3DPipelineTests(unittest.TestCase):
    def test_same_calls_and_bitwise_unchanged_image_score_arrays(self):
        import modules.extract_pose_with_roi as extractor
        frames=[np.zeros((256,256,3),np.uint8) for _ in range(9)]
        info={'scale':1.,'x1':3,'y1':4,'x_offset':0,'y_offset':0}
        infos=[info.copy() for _ in frames]
        baseline=FakeLandmarker();observed=FakeLandmarker()
        with patch.object(extractor,'create_landmarker',return_value=baseline):
            before=extractor.extract_pose_with_roi(frames,infos,60,'fixture')
        capture=Pose3DCapture(np.arange(9)/60,False,1920,1080,60)
        with patch.object(extractor,'create_landmarker',return_value=observed):
            after=extractor.extract_pose_with_roi(frames,infos,60,'fixture',world_capture=capture)
        for a,b in zip(before,after):
            self.assertEqual(a.tobytes(),b.tobytes())
        self.assertEqual(baseline.times,observed.times)
        self.assertEqual(len(observed.times),9)
        data=capture.finish()
        np.testing.assert_array_equal(data['world_raw'][0],WORLD)
        self.assertFalse(np.allclose(data['world_raw'][0],after[0][0],equal_nan=True))
        self.assertEqual(data['additional_pose_inference_calls'],0)

    def test_observer_failure_does_not_change_image_score(self):
        import modules.extract_pose_with_roi as extractor
        frames=[np.zeros((256,256,3),np.uint8) for _ in range(9)]
        infos=[{'scale':1.,'x1':0,'y1':0,'x_offset':0,'y_offset':0} for _ in frames]
        class Broken(Pose3DCapture):
            def record(self,*args):raise RuntimeError('synthetic observer failure')
        broken=Broken(np.arange(9)/60,False,1920,1080,60)
        with patch.object(extractor,'create_landmarker',side_effect=[FakeLandmarker(),FakeLandmarker()]):
            a=extractor.extract_pose_with_roi(frames,infos,60,'fixture')
            b=extractor.extract_pose_with_roi(frames,infos,60,'fixture',world_capture=broken)
        for x,y in zip(a,b):self.assertEqual(x.tobytes(),y.tobytes())
        self.assertEqual(broken.error['code'],'WORLD_CAPTURE_FAILED')
        with self.assertRaises(Pose3DError):broken.finish()

    def test_same_decode_pixels_and_exact_pts_without_second_read(self):
        from modules.utils.video_roi_left import read_video
        frames=[np.full((4,6,3),i,np.uint8) for i in range(3)]
        class Capture:
            def __init__(self,*args):self.index=0
            def isOpened(self):return True
            def read(self):
                if self.index==3:return False,None
                v=frames[self.index].copy();self.index+=1;return True,v
            def get(self,key):
                import cv2
                return 60 if key==cv2.CAP_PROP_FPS else [100,116.7,134.2][self.index-1]
            def release(self):pass
        with patch('modules.utils.video_roi_left.cv2.VideoCapture',Capture):
            a,rate=read_video('fixture');pts=[];b,rate2=read_video('fixture',timestamps_out=pts)
        for x,y in zip(a,b):np.testing.assert_array_equal(x,y)
        self.assertEqual(rate,rate2)
        np.testing.assert_allclose(pts,[.1,.1167,.1342],rtol=0,atol=1e-15)

    def test_left_restoration_swaps_and_reflects_once(self):
        right=capture_data(mirrored=False);left=capture_data(mirrored=True)
        before=left['world_raw'].copy()
        r=restore_world(right);l=restore_world(left)
        expected=r[0][:,[1,0,3,2,5,4,7,6,9,8,11,10]].copy();expected[...,0]*=-1
        np.testing.assert_array_equal(l[0],expected)
        np.testing.assert_array_equal(left['world_raw'],before)
        self.assertEqual(l[5],[1,0,3,2,5,4,7,6,9,8,11,10])

    def test_full_packet_preserves_raw_nulls_masks_timestamps_and_score_arrays(self):
        data=capture_data(mirrored=True);data['world_raw'][4,4]=np.nan
        data['image_quality']['combined_missing'][4,4]=True
        sk=skeleton(data);before=copy.deepcopy(sk)
        packet=build_pose3d(sk,analysis_id='a'*32,user_id='real-owner',source_sha256='b'*64)
        packet=json.loads(json.dumps(packet,allow_nan=False))
        self.assertEqual(packet['data_kind'],'analysis');self.assertEqual(packet['analysis_id'],'a'*32)
        self.assertEqual(packet['id'],packet['analysis_id'])
        self.assertEqual(packet['source_provenance']['source_video_sha256'],'b'*64)
        self.assertNotIn('sample',packet['data_kind'])
        self.assertIsNone(packet['raw_estimation']['world_raw'][4][4])
        self.assertIsNone(packet['frames'][4]['positions'][5])
        raw=packet['final_display_data']['raw_orientation'];display=packet['final_display_data']['display_orientation']
        for a,b,f in zip(raw['frames'],display['frames'],packet['frames']):
            self.assertEqual(a['p2'],b['p2'])
            self.assertEqual([p is None for p in a['positions']],[p is None for p in b['positions']])
            self.assertEqual(a['timestamp_s'],b['timestamp_s']);self.assertEqual(f['timestamp_s'],a['timestamp_s'])
        for name in ['landmarks','landmarks_pixel','visibility']:
            np.testing.assert_array_equal(getattr(sk,name),getattr(before,name))
        np.testing.assert_array_equal(sk.pose3d_capture['world_raw'],before.pose3d_capture['world_raw'])
        self.assertEqual(packet['final_display_data']['processing']['smoothing_passes'],1)
        self.assertFalse(packet['final_display_data']['processing']['interpolation'])

    def test_missing_world_is_explicit_not_sample_fallback(self):
        sk=skeleton();sk.pose3d_capture=None
        with self.assertRaisesRegex(Pose3DError,'3D World'):build_pose3d(sk,analysis_id='x',user_id='u',source_sha256='a'*64)
        sk.pose3d_error={'code':'INVALID_VIDEO_PTS','message':'invalid timeline'}
        with self.assertRaisesRegex(Pose3DError,'invalid timeline'):build_pose3d(sk,analysis_id='x',user_id='u',source_sha256='a'*64)

    def test_invalid_pts_rejected_without_changing_score(self):
        sk=skeleton();sk.pose3d_capture['decoded_pts_s'][3]=sk.pose3d_capture['decoded_pts_s'][2]
        with self.assertRaises(Pose3DError):build_pose3d(sk,analysis_id='x',user_id='u',source_sha256='a'*64)
        self.assertTrue(np.all(sk.landmarks==1))

    def test_frozen_policy_code_is_exact_research_source(self):
        self.assertEqual(P2_SHA,'f7c94e89ce23e2e03a705c51ab1ba7ac53495d4ae1b98f25ea822f2e26312dbf')


if __name__=='__main__':unittest.main()
