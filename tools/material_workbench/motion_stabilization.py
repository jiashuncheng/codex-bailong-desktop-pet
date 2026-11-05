"""Optional slow scale/vertical drift correction; keep the source poses and timing."""
import copy,math
import numpy as np
from cartoon import body_anchor
from media import frames

def analyse(path,matcher,log=lambda *a,**k:None):
    samples=[];times=[];durations=[];timestamp=0
    def sample(image,index,time):
        match=matcher.match(image)
        if match and match['score']>=.70:
            try:foot=body_anchor(image,match)
            except ValueError:foot=None
            if foot:samples.append(dict(frame=index,time=time,scale=match['scale'],footY=foot[1],score=match['score']))
    iterator=frames(path)
    try:
        for index,(image,ms) in enumerate(iterator):
            times.append(timestamp);durations.append(ms)
            if index%12==0:
                sample(image,index,timestamp)
                log('分析人物尺度和脚底漂移',frame=index+1)
            timestamp+=ms
    finally:iterator.close()
    if times and (len(times)-1)%12:sample(image,len(times)-1,times[-1])
    if len(samples)<3 or samples[0]['frame']>12 or samples[-1]['time']<timestamp*.65:
        raise ValueError('全段可靠头脸样本不足，暂不自动稳定；可关闭稳定选项保留原动作')
    raw_scale=np.array([s['scale'] for s in samples],float)
    if raw_scale.max()/raw_scale.min()>1.5:raise ValueError('头脸识别或镜头变化过大，拒绝猜测稳定参数')
    knots=np.array([s['time'] for s in samples],float)
    def smooth(values):
        curve=np.interp(times,knots,values)
        sigma=max(1.,160/max(1,float(np.median(durations))));radius=math.ceil(3*sigma)
        x=np.arange(-radius,radius+1);kernel=np.exp(-.5*(x/sigma)**2);kernel/=kernel.sum()
        return np.convolve(np.pad(curve,(radius,radius),mode='edge'),kernel,mode='valid')
    scales=smooth(raw_scale);feet=smooth([s['footY'] for s in samples])
    # Anchor to the observed first pose; filter only slow camera drift, not limbs.
    gains=scales[0]/scales
    feet=feet-feet[0]+samples[0]['footY']
    return dict(schema=1,frames=len(times),gains=gains.tolist(),footY=feet.tolist(),samples=samples,
        scaleDriftPercent=round((raw_scale.max()/raw_scale.min()-1)*100,2),
        footDriftPixels=round(max(s['footY'] for s in samples)-min(s['footY'] for s in samples),2))

def transform_at(record,index=0):
    transform=copy.deepcopy(record['transform']);profile=record.get('stabilization')
    if profile:
        index=max(0,min(int(index),profile['frames']-1))
        transform['scale']*=profile['gains'][index]
        transform['anchor'][1]=profile['footY'][index]
    return transform

def geometry_transforms(record):
    profile=record.get('stabilization')
    if not profile:return [record['transform']]
    return [transform_at(record,index) for index in range(profile['frames'])]
