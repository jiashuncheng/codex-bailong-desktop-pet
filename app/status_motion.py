"""Three liquid identities morph into task glyphs on a single motion clock."""
import math
from typing import NamedTuple

BUSY_RING_RADIUS=2.2
BUSY_RING_STROKE=0.
BUSY_BREATH_SECONDS=1.8
BUSY_ROTATION_SECONDS=10.8
MORPH_SECONDS=.48


class Part(NamedTuple):
    x:float
    y:float
    length:float=0.       # Half the straight segment of a vertical capsule.
    radius:float=1.
    hole:float=0.         # Inner capsule radius; zero means a solid shape.
    angle:float=0.        # Degrees, about the part's own center.
    opacity:float=1.
    mint:float=0.         # The third ball retains its contrasting identity.
    bond:float=0.         # Soft neck to the next ball, by identity (not slot).
    warm:float=0.         # Offline warning palette, interpolated with geometry.


def smootherstep(x):
    x=max(0.,min(1.,x));return x*x*x*(x*(x*6-15)+10)


def busy_liquid_parts(elapsed):
    # Exact choreography from the accepted preview. Six beats close both the
    # whole rotation and each ball's identity, including the alternating neck.
    elapsed=max(0.,elapsed)%BUSY_ROTATION_SECONDS
    beat=int(elapsed/BUSY_BREATH_SECONDS);phase=elapsed-beat*BUSY_BREATH_SECONDS
    first,second=beat%3,(beat+1)%3
    turn=-math.pi/2+math.tau*elapsed/BUSY_ROTATION_SECONDS
    contact=smootherstep((phase-.70)/.19)*(1-smootherstep((phase-1.12)/.29))
    bond=smootherstep((phase-.65)/.16)*(1-smootherstep((phase-1.22)/.24))
    parts=[]
    for i in range(3):
        progress=smootherstep((phase-.20-(i-1)*.02)/.46)
        radius=4-1.25*math.sin(math.pi*progress)**2
        bend=1 if i==first else -1 if i==second else 0
        angle=turn+(i+beat+progress)*math.tau/3+bend*math.pi/10*contact
        parts.append(Part(8+radius*math.cos(angle),8+radius*math.sin(angle),
                          radius=BUSY_RING_RADIUS,mint=float(i==2),bond=bond if i==first else 0.))
    return tuple(parts)


def busy_ring_centers(elapsed):
    """Compatibility helper for callers measuring the three particle centers."""
    return tuple((p.x,p.y) for p in busy_liquid_parts(elapsed))


def rotate_parts(parts,angle):
    radians=math.radians(angle);c,s=math.cos(radians),math.sin(radians)
    return tuple(p._replace(x=8+(p.x-8)*c-(p.y-8)*s,
                            y=8+(p.x-8)*s+(p.y-8)*c,angle=p.angle+angle) for p in parts)


class GlyphMotion:
    """Retarget from the current geometry, including its incoming velocity."""
    def __init__(self,now=0.):
        self.state='idle';self.since=now;self.started=None
        self.source=None;self.velocity=None;self.attention_at=None

    def shaking(self,now):
        return self.state=='attention' and self.attention_at is not None and 0<=now-self.attention_at<1.2

    def moving(self,now):
        return (self.started is not None and now-self.started<MORPH_SECONDS
                or self.state in ('busy','waiting') or self.shaking(now))

    def steady(self,now):
        elapsed=max(0.,now-self.since)
        if self.state=='busy':
            return busy_liquid_parts(elapsed)
        if self.state=='waiting':
            return tuple(Part(x,8,radius=1.55+.18*math.sin(math.tau*elapsed/2.0-i*.55),
                              mint=float(i==2)) for i,x in enumerate((3.5,8,12.5)))
        if self.state=='paused':
            return (Part(5.6,6.6,1.4,1.2),Part(5.6,9.4,1.4,1.2),Part(10.4,8,2.8,1.2,mint=1))
        if self.state in ('attention','warning'):
            warm=float(self.state=='warning')
            parts=(Part(8,5.1,1.05,1.25,warm=warm),Part(8,7.2,1.05,1.25,warm=warm),
                   Part(8,12,radius=1.4,mint=1,warm=warm))
            if self.shaking(now):
                # Two gentle oscillations, both starting and ending at rest.
                t=(now-self.attention_at)/1.2
                parts=rotate_parts(parts,9*math.sin(math.tau*2*t)*math.sin(math.pi*t)**2)
            return parts
        if self.state=='complete':
            angle=math.degrees(math.atan2(4.8,5.2));length=math.hypot(2.4,2.6)/2
            return (Part(5.75,9.25,math.sqrt(2.5**2*2)/2,1.1,angle=-45),
                    Part(8.2,9.2,length,1.1,angle=angle),
                    Part(10.6,6.6,length,1.1,angle=angle,mint=1))
        return (Part(7.4,8,radius=1.7),Part(8,8,opacity=0),Part(9,8,radius=1.1,mint=1,opacity=.75))

    def sample(self,now):
        target=self.steady(now)
        if self.started is None or now-self.started>=MORPH_SECONDS:return target
        t=max(0.,(now-self.started)/MORPH_SECONDS)
        ease=t*t*(3-2*t)
        # Hermite's initial tangent carries rotation into the gathering motion.
        coast=MORPH_SECONDS*t*(1-t)**2
        parts=[]
        for start,end,velocity in zip(self.source,target,self.velocity):
            values=[a+(b-a)*ease+v*coast for a,b,v in zip(start,end,velocity)]
            x,y,length,radius,hole,angle,opacity,mint,bond,warm=values
            length=max(0.,length);radius=max(.05,radius)
            hole=max(0.,min(radius,hole));opacity=max(0.,min(1.,opacity))
            mint=max(0.,min(1.,mint));bond=max(0.,min(1.,bond));warm=max(0.,min(1.,warm))
            # Keep every intermediate silhouette inside the fixed 16px canvas.
            radians=math.radians(angle)
            rx=abs(math.sin(radians))*length+radius
            ry=abs(math.cos(radians))*length+radius
            x=max(.4+rx,min(15.6-rx,x));y=max(.4+ry,min(15.6-ry,y))
            parts.append(Part(x,y,length,radius,hole,angle,opacity,mint,bond,warm))
        return tuple(parts)

    def set_state(self,state,now,animate=True):
        if state==self.state:return False
        source=self.sample(now)
        previous=self.sample(now-.002)
        self.velocity=tuple(tuple((a-b)/.002 for a,b in zip(p,q)) for p,q in zip(source,previous))
        self.source=source;self.state=state;self.since=now
        self.started=now if animate else None
        self.attention_at=now+MORPH_SECONDS if state=='attention' and animate else None
        return True

    def settle(self):
        self.started=None;self.attention_at=None

    def notify_again(self,now):
        if self.state=='attention' and not self.shaking(now):
            self.attention_at=max(now,self.started+MORPH_SECONDS) if self.started is not None else now
