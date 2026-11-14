"""Generated clip -> engine frame sequence + analysis.
usage: python tools/prep_video.py in.mp4 clipname [--fps 30] [--width 1280] [--pose]
writes assets/video/<clip>/f_00001.jpg..., meta.json {fps,n,w,h,dur,ext}, and optional pose.json (33 landmarks/frame, normalized)."""
import os, json, shutil, subprocess, argparse, tempfile
ap = argparse.ArgumentParser(); ap.add_argument('src'); ap.add_argument('clip'); ap.add_argument('--fps', type=float, default=30); ap.add_argument('--width', type=int, default=1280); ap.add_argument('--pose', action='store_true')
a = ap.parse_args()
target = os.path.abspath(f'assets/video/{a.clip}')
os.makedirs(os.path.dirname(target), exist_ok=True)
work = tempfile.mkdtemp(prefix='.prep-', dir=os.path.dirname(target))
out = os.path.join(work, 'take'); os.mkdir(out)
backup = os.path.join(work, 'previous')
try:
    if os.path.exists(target):
        for name in os.listdir(target):
            if name.startswith(('f_', 'm_')) or name in ('meta.json', 'pose.json', 'track.json'):
                continue
            src = os.path.join(target, name); dst = os.path.join(out, name)
            if os.path.isdir(src): shutil.copytree(src, dst)
            else: shutil.copy2(src, dst)
    subprocess.run(['ffmpeg','-loglevel','error','-y','-i',a.src,'-vf',f'fps={a.fps},scale={a.width}:-2:flags=lanczos','-q:v','2',f'{out}/f_%05d.jpg'], check=True)
    n = len([f for f in os.listdir(out) if f.startswith('f_')])
    pr = json.loads(subprocess.run(['ffprobe','-v','error','-show_entries','stream=width,height,duration,r_frame_rate','-of','json',f'{a.src}'],capture_output=True,text=True,check=True).stdout)['streams'][0]
    from PIL import Image
    w,h = Image.open(f'{out}/f_00001.jpg').size
    import numpy as _np


    def load_json(path):
        with open(path) as f:
            return json.load(f)


    def save_json(obj, path, **kw):
        with open(path, 'w') as f:
            json.dump(obj, f, **kw)


    lums=[_np.asarray(Image.open(f'{out}/f_{i:05d}.jpg').convert('L'),dtype=_np.float32)/255 for i in range(1,n+1,max(1,n//12))]
    L=_np.concatenate([x.ravel() for x in lums])
    meta_l={'lumLo': round(float(_np.percentile(L,8)),3), 'lumHi': round(float(_np.percentile(L,99.5)),3)}
    meta = {**meta_l, 'fps': a.fps, 'n': n, 'w': w, 'h': h, 'dur': n / a.fps, 'ext': 'jpg', 'src': os.path.basename(a.src), 'src_fps': pr.get('r_frame_rate')}
    if a.pose:
        import mediapipe as mp, cv2
        pose = mp.solutions.pose.Pose(static_image_mode=False, model_complexity=1)
        P = []
        for i in range(1, n+1):
            im = cv2.cvtColor(cv2.imread(f'{out}/f_{i:05d}.jpg'), cv2.COLOR_BGR2RGB); r = pose.process(im)
            P.append([[round(l.x,4), round(l.y,4), round(l.visibility,3)] for l in r.pose_landmarks.landmark] if r.pose_landmarks else None)
        save_json(P, f'{out}/pose.json'); meta['pose'] = True
    save_json(meta, f'{out}/meta.json', indent=1)

    if os.path.exists(target): os.rename(target, backup)
    try:
        os.rename(out, target)
    except OSError:
        if os.path.exists(backup): os.rename(backup, target)
        raise
    if os.path.exists(backup): shutil.rmtree(backup)
    print(meta)
finally:
    # Keep the previous take recoverable if promotion and rollback both fail.
    if not os.path.exists(backup): shutil.rmtree(work)
