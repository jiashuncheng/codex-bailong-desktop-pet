"""Scale a chibi character from its facial features, excluding large props."""
from pathlib import Path
import math
import numpy as np
from PIL import Image,ImageDraw

def area_sum(a,h,w):
    c=np.pad(a.cumsum(0).cumsum(1),((1,0),(1,0)))
    return c[h:,w:]-c[:-h,w:]-c[h:,:-w]+c[:-h,:-w]

class CartoonFace:
    def __init__(self,reference,box=(255,278,445,334)):
        self.reference=Image.open(reference).convert('RGBA')
        self.box=list(box);self.template=self.reference.crop(box).convert('L')
    def match(self,image):
        im=image.convert('RGBA');bbox=im.getchannel('A').point(lambda a:255 if a>=100 else 0).getbbox()
        if not bbox:return None
        bg=Image.new('RGB',im.size,'white');bg.paste(im,mask=im.getchannel('A'))
        factor=min(.5,640/max(im.size))
        small=bg.resize((max(1,round(im.width*factor)),max(1,round(im.height*factor))),Image.Resampling.BILINEAR)
        a=np.asarray(small.convert('L'),dtype=np.float64)/255
        # Search relative to the visible height, with enough range for an overhead prop.
        expected=(bbox[3]-bbox[1])/608
        low=max(.22,expected*.48);high=min(4.,expected*1.55)
        best=None
        for scale in np.linspace(low,high,35):
            tw=max(10,round(self.template.width*factor*scale));th=max(6,round(self.template.height*factor*scale))
            if tw>=a.shape[1] or th>=a.shape[0]:continue
            t=np.asarray(self.template.resize((tw,th),Image.Resampling.BILINEAR),dtype=np.float64)/255
            t-=t.mean();energy=float(np.sum(t*t))
            if energy<1e-7:continue
            shape=(a.shape[0]+th-1,a.shape[1]+tw-1)
            corr=np.fft.irfftn(np.fft.rfftn(a,s=shape,axes=(0,1))*np.fft.rfftn(t[::-1,::-1],s=shape,axes=(0,1)),s=shape,axes=(0,1)).real[th-1:a.shape[0],tw-1:a.shape[1]]
            variance=np.maximum(area_sum(a*a,th,tw)-area_sum(a,th,tw)**2/(th*tw),1e-7)
            corr/=np.sqrt(variance*energy)
            yy=np.arange(corr.shape[0])[:,None]
            allowed=(yy>=bbox[1]*factor)&(yy+th/2<=(bbox[1]+(bbox[3]-bbox[1])*.82)*factor)
            corr=np.where(allowed,corr,-1)
            y,x=np.unravel_index(np.argmax(corr),corr.shape);score=float(corr[y,x])
            if best is None or score>best['score']:
                best=dict(scale=float(scale),score=score,box=[x/factor,y/factor,(x+tw)/factor,(y+th)/factor])
        return best

def calibrate(samples,override=None):
    override=override or {}
    if 'scale' in override:
        scale=float(override['scale']);matches=[]
    else:
        matches=[s for s in samples if s and s['score']>=.64]
        if len(matches)<2:raise ValueError('未可靠匹配白龙头脸；请设置本素材的固定scale/anchor，或使用正面起始图重新生成')
        values=np.array([s['scale'] for s in matches]);median=float(np.median(values))
        if np.std(values)/median>.12:raise ValueError('起始阶段的头脸大小不稳定，需人工指定固定缩放')
        scale=1/median
    if not math.isfinite(scale) or not .2<=scale<=5:raise ValueError('人物缩放参数异常')
    return scale,matches

def body_anchor(image,face_match):
    """Use the component containing the face, without deleting detached particles."""
    alpha=np.asarray(image.getchannel('A'));h,w=alpha.shape
    ph=math.ceil(h/4)*4;pw=math.ceil(w/4)*4
    padded=np.zeros((ph,pw),bool);padded[:h,:w]=alpha>=100
    pooled=padded.reshape(ph//4,4,pw//4,4).any(axis=(1,3))
    b=face_match['box'];cx=(b[0]+b[2])/2;cy=(b[1]+b[3])/2
    small=Image.fromarray(np.uint8(pooled)*255).copy()
    seed=(max(0,min(pw//4-1,int(cx//4))),max(0,min(ph//4-1,int(cy//4))))
    if not pooled[seed[1],seed[0]]:raise ValueError('脸部锚点不在人物实体上')
    ImageDraw.floodfill(small,seed,128)
    keep=np.repeat(np.repeat(np.asarray(small)==128,4,axis=0),4,axis=1)[:h,:w]
    solid=(alpha>=100)&keep
    rows=np.flatnonzero(solid.sum(1)>=max(5,round(w*.006)))
    if not len(rows):raise ValueError('无法从人物主体确定落脚位置')
    bottom=int(rows[-1])+1;top=int(rows[0]);band=solid[max(0,bottom-max(8,round((bottom-top)*.035))):bottom]
    _,xs=np.nonzero(band)
    if not len(xs):raise ValueError('缺少有效落脚实体')
    return [float(np.median(xs)),float(bottom)]
