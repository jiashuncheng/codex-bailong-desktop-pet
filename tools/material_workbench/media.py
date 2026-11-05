"""Local, lossless media preparation. Never changes per-frame geometry."""
from pathlib import Path
import hashlib, json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageFilter
import imageio_ffmpeg

HIDDEN = 0x08000000 if os.name == 'nt' else 0
REVISION = 'real-fixed-face-v1'

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()

def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def frames(path):
    path = Path(path)
    if path.suffix.lower() in ('.webp', '.png', '.gif'):
        with Image.open(path) as im:
            for i in range(getattr(im, 'n_frames', 1)):
                im.seek(i); im.load()
                yield im.convert('RGBA'), int(im.info.get('duration', 100))
        return
    # FFmpeg's native VP9 decoder drops WebM alpha. Explicit libvpx is essential.
    args = ['-c:v', 'libvpx-vp9'] if path.suffix.lower() == '.webm' else []
    reader = imageio_ffmpeg.read_frames(str(path), pix_fmt='rgba', bits_per_pixel=32, input_params=args)
    try:
        info = next(reader); fps = float(info['fps']); size = info['size']
        if not math.isfinite(fps) or fps <= 0: raise ValueError('无效帧率')
        for i, raw in enumerate(reader):
            # Integer timestamp differences preserve 24/30/29.97 fps total duration.
            yield Image.frombytes('RGBA', size, raw), round((i+1)*1000/fps)-round(i*1000/fps)
    finally: reader.close()

class Face:
    """YuNet inference; OpenCV's documented decoder implemented in NumPy."""
    def __init__(self, base, runtime):
        sys.path.insert(0, str(runtime)); import onnxruntime as ort
        options=ort.SessionOptions(); options.intra_op_num_threads=2; options.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(Path(base)/'models/yunet.onnx'), options,
                                         providers=['CPUExecutionProvider'])
        self.side=int(self.session.get_inputs()[0].shape[-1])
    def detect(self, im):
        # Crop transparent padding first, ensuring small full-body faces remain detectable.
        box=im.getchannel('A').point(lambda a: 255 if a>=24 else 0).getbbox()
        if not box: return None
        left,top,right,bottom=box; crop=im.crop(box)
        rgb=Image.new('RGB',crop.size,(180,180,180)); rgb.paste(crop,mask=crop.getchannel('A'))
        factor=self.side/max(rgb.size); w=max(1,round(rgb.width*factor)); h=max(1,round(rgb.height*factor))
        scaled=rgb.resize((w,h),Image.Resampling.BILINEAR)
        image=Image.new('RGB',(self.side,self.side)); image.paste(scaled,(0,0))
        tensor=np.asarray(image,dtype=np.float32)[:,:,::-1].transpose(2,0,1)[None].copy()
        output=dict(zip([o.name for o in self.session.get_outputs()],
                        self.session.run(None,{self.session.get_inputs()[0].name:tensor})))
        candidates=[]
        for stride in (8,16,32):
            scores=np.sqrt(np.clip(output[f'cls_{stride}'].reshape(-1),0,1)*
                           np.clip(output[f'obj_{stride}'].reshape(-1),0,1))
            boxes=output[f'bbox_{stride}'].reshape(-1,4)
            for k in np.flatnonzero(scores>.78):
                r,c=divmod(int(k),self.side//stride); b=boxes[k]
                bw,bh=np.exp(b[2:])*stride/factor
                cx=(c+float(b[0]))*stride/factor+left
                cy=(r+float(b[1]))*stride/factor+top
                if cy>top+(bottom-top)*.62: continue  # No faces in shoes/props.
                candidates.append([float(cx-bw/2),float(cy-bh/2),float(bw),float(bh),float(scores[k])])
        if not candidates:return None
        best=max(candidates,key=lambda b:b[4])
        # Multiple detections of the same face are expected before NMS; reject a second person.
        for b in candidates:
            if abs((b[0]+b[2]/2)-(best[0]+best[2]/2))>max(b[2],best[2])*1.5:
                raise ValueError('检测到多个人脸，请只保留一个人物')
        return best

class GreenMatte:
    def __init__(self, base, runtime):
        model=Path(base)/'models/u2netp.onnx'
        if not model.is_file():
            raise RuntimeError('绿幕模型尚未安装：请按工作台 README 安装 requirements-matting.txt 并运行 download_models.py。透明 WebM/WebP 无需此模型。')
        sys.path.insert(0,str(runtime)); import onnxruntime as ort
        opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(Path(base)/'models/u2netp.onnx'),opts,
                                         providers=['CPUExecutionProvider'])
        self.oldalpha=None; self.oldrgb=None
    def apply(self, image):
        rgb=image.convert('RGB'); a=np.asarray(rgb,dtype=np.float32);h,w=a.shape[:2]
        samples=a[::24,::24]; sg=samples[:,:,1]-np.maximum(samples[:,:,0],samples[:,:,2])
        good=(sg>70)&(samples[:,:,1]>110)
        if good.mean()<.18:raise ValueError('不是可稳定处理的均匀绿底；请提供透明素材或纯绿底视频')
        yy,xx=np.mgrid[0:h,0:w].astype(np.float32);xx/=max(w-1,1);yy/=max(h-1,1)
        features=np.stack([np.ones_like(xx),xx,yy,xx*yy,xx*xx,yy*yy],-1)
        coef=np.linalg.lstsq(features[::24,::24][good],samples[good],rcond=None)[0]
        bg=features@coef
        small=np.asarray(rgb.resize((320,320),Image.Resampling.LANCZOS),dtype=np.float32)
        small/=max(float(small.max()),1)
        small=(small-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
        pred=self.session.run(None,{self.session.get_inputs()[0].name:small.transpose(2,0,1)[None]})[0][0,0]
        pred=(pred-pred.min())/max(float(pred.max()-pred.min()),1e-7)
        probability=np.asarray(Image.fromarray(np.uint8(pred*255)).resize((w,h),Image.Resampling.BILINEAR),dtype=np.float32)/255
        support=Image.fromarray(np.uint8(pred>.015)*255).filter(ImageFilter.MaxFilter(9)).resize((w,h),Image.Resampling.BILINEAR)
        excess=a[:,:,1]-np.maximum(a[:,:,0],a[:,:,2]);be=np.maximum(bg[:,:,1]-np.maximum(bg[:,:,0],bg[:,:,2]),80)
        alpha=np.clip((1-excess/be-.045)/.90,0,1)*np.asarray(support,dtype=np.float32)/255
        alpha[(probability>.8)&(excess<be*.28)]=1
        alpha[alpha>.94]=1;alpha[alpha<.045]=0
        if self.oldalpha is not None:
            stable=(np.abs(alpha-self.oldalpha)<.1)&(alpha>.045)&(alpha<.94)&(np.abs(a-self.oldrgb).max(-1)<12)
            alpha[stable]=alpha[stable]*.88+self.oldalpha[stable]*.12
        self.oldalpha=alpha.copy();self.oldrgb=a.copy()
        color=np.clip((a-bg*(1-alpha[:,:,None]))/np.maximum(alpha[:,:,None],.07),0,255)
        color[:,:,1]-=np.maximum(color[:,:,1]-np.maximum(color[:,:,0],color[:,:,2])-3,0)*.92
        alpha=np.asarray(Image.fromarray(np.uint8(np.rint(alpha*255))).filter(ImageFilter.MedianFilter(3)))
        # Propagate nearby solid foreground colour only into soft boundary pixels.
        solid=Image.fromarray(np.uint8(alpha>251)*255).filter(ImageFilter.MinFilter(3))
        weights=np.asarray(solid.filter(ImageFilter.GaussianBlur(2)),dtype=np.float32)/255
        numerator=np.uint8(np.clip(color,0,255)*np.asarray(solid,dtype=np.float32)[:,:,None]/255)
        estimate=np.asarray(Image.fromarray(numerator).filter(ImageFilter.GaussianBlur(2)),dtype=np.float32)/np.maximum(weights[:,:,None],.001)
        af=alpha.astype(np.float32)/255
        mix=(.2+.65*(1-af))*((alpha>0)&(alpha<251)&(weights>.06))
        color=np.clip(color+(estimate-color)*mix[:,:,None],0,255)
        r,g,b=color[:,:,0],color[:,:,1],color[:,:,2]
        warm=(r>b+12)&(g>b+10)&(alpha>0)&((alpha<251)|(g>r-3))
        color[:,:,1]=np.where(warm,np.minimum(g,.65*r+.35*b+4),g)
        rgba=np.dstack([np.uint8(np.rint(np.clip(color,0,255))),alpha]);rgba[alpha==0,:3]=0
        return Image.fromarray(rgba)

def inspect(path, face=None, sample_faces=True, reject_source_clipping=True):
    union=None; boxes=[]; faces=[]; durations=[];touch=[];first=None;size=None
    for i,(im,duration) in enumerate(frames(path)):
        if size and im.size!=size:raise ValueError('帧画布变化')
        size=im.size; alpha=im.getchannel('A');a=np.asarray(alpha)
        if a.min()!=0 or a.max()<240:raise ValueError(f'第{i+1}帧没有有效透明背景或主体')
        box=alpha.getbbox()  # All nonzero alpha, not only an arbitrary threshold.
        if not box:raise ValueError(f'第{i+1}帧人物消失')
        union=list(box) if union is None else [min(union[0],box[0]),min(union[1],box[1]),max(union[2],box[2]),max(union[3],box[3])]
        if box[0]<=0 or box[1]<=0 or box[2]>=im.width or box[3]>=im.height:touch.append(i)
        if first is None:first=im.copy()
        boxes.append(list(box));durations.append(duration)
        if face and sample_faces and i in (0,3,6,12,18,24):
            found=face.detect(im)
            if found:faces.append(found)
        if sum(durations)>60000 or i>=3600:raise ValueError('单段素材超过60秒或3600帧')
    if len(boxes)<2:raise ValueError('需要至少两帧的动画素材')
    if touch and reject_source_clipping:raise ValueError(f'原片有{len(touch)}帧人物/道具碰到画布边缘，可能已裁切；请补留白后重新导出')
    return dict(size=list(size),frames=len(boxes),durationMs=sum(durations),durations=durations,
                union=union,firstBox=boxes[0],faces=faces,
                sourceEdgeTouchFrames=len(touch),sourceEdgeTouchExamples=touch[:12]),first

def write_animation(path, iterator):
    """Lossless WebP; integer per-frame durations, no dropped duplicate frames."""
    from PIL import _webp
    encoder=None;timestamp=0;count=0;size=None
    for im,ms in iterator:
        if encoder is None:
            size=im.size
            encoder=_webp.WebPAnimEncoder(im.size,0,0,False,9,17,False,False)
        if size!=im.size:raise ValueError('画布不一致')
        # Pillow's own plugin uses this API; unlike FFmpeg it preserves variable timing.
        im.load();encoder.add(im.getim(),timestamp,True,100,100,1)
        timestamp+=int(ms);count+=1
    if encoder is None:raise ValueError('空动画')
    encoder.add(None,timestamp,True,100,100,0)
    data=encoder.assemble('', '', '')
    Path(path).write_bytes(data)
    return count,timestamp

def foot_anchor(first):
    a=np.asarray(first.getchannel('A'));ys,xs=np.nonzero(a>=100)
    if not len(xs):raise ValueError('没有实体人物')
    bottom=int(ys.max())+1;top=int(ys.min());band=(ys>=bottom-max(8,round((bottom-top)*.035)))
    return [float(np.median(xs[band])),float(bottom)]

def fit_transform(info, first, reference_face, override=None):
    override=override or {}; found=info['faces']
    if 'scale' in override:scale=float(override['scale'])
    elif len(found)>=2:
        heights=np.array([b[3] for b in found]);median=float(np.median(heights))
        if np.std(heights)/median>.14:raise ValueError('人脸尺度不稳定，请设置本素材固定scale')
        scale=reference_face/median
    else:raise ValueError('未可靠识别正面脸，需在配置 overrides 中指定固定scale和anchor')
    if not math.isfinite(scale) or not .25<=scale<=4:raise ValueError('人物缩放异常')
    anchor=override.get('anchor',foot_anchor(first))
    if len(anchor)!=2 or not all(math.isfinite(float(v)) for v in anchor):raise ValueError('anchor无效')
    return dict(scale=scale,anchor=list(map(float,anchor)))

def placed(im, transform, canvas, anchor):
    from alignment import placement_rect
    # One fixed affine transform for every frame. Pillow RGBA resize is premultiplied.
    x,y,w,h=placement_rect(transform,anchor)
    if (w,h)!=im.size:im=im.resize((w,h),Image.Resampling.LANCZOS)
    bbox=im.getchannel('A').getbbox()
    if bbox and (x+bbox[0]<0 or y+bbox[1]<0 or x+bbox[2]>canvas or y+bbox[3]>canvas):
        raise ValueError('缩放后可见内容越界，拒绝裁切')
    out=Image.new('RGBA',(canvas,canvas));out.paste(im,(x,y))
    return out
