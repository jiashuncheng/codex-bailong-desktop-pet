"""Three liquid identities morph into task glyphs on a single motion clock."""
import math
from typing import NamedTuple

BUSY_RING_RADIUS=2.25
BUSY_RING_STROKE=0.
BUSY_BREATH_SECONDS=2.04
BUSY_ROTATION_SECONDS=BUSY_BREATH_SECONDS*12
BUSY_GLOBAL_TURNS=2  # One extra full orbit keeps the faster motion loop-closed.
BUSY_OUTER_SPEED=2.5  # Only the steady outer orbit; exchange/adhesion timing stays unchanged.
IDLE_ROTATION_SECONDS=18.
BUSY_PAIRS=((1,2),(2,0),(0,1),(2,1),(1,0),(0,2))
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
    rose:float=0.
    satin:float=0.
    sxx:float=1.          # Symmetric area-preserving stretch; no angle wrap.
    syy:float=1.
    sxy:float=0.
    depth:float=0.        # Painter order; changes only while balls are separate.


def smootherstep(x):
    x=max(0.,min(1.,x));return x*x*x*(x*(x*6-15)+10)


def busy_liquid_parts(elapsed):
    """Accepted A preview: alternate center passes and brisk orbital swaps."""
    elapsed=max(0.,elapsed)%BUSY_ROTATION_SECONDS
    beat=int(elapsed/BUSY_BREATH_SECONDS);phase=elapsed/BUSY_BREATH_SECONDS-beat
    crossing=beat%2==0;progress=smootherstep((phase-.14)/.22)
    settle=math.sin(math.pi*max(0.,min(1.,(phase-.32)/.11)))**2
    base=math.ceil(beat/2)*math.pi+math.floor(beat/2)*math.tau/3
    turn=math.tau*BUSY_GLOBAL_TURNS*BUSY_OUTER_SPEED*elapsed/BUSY_ROTATION_SECONDS+(math.floor(beat/2)+(0 if crossing else progress))*math.pi/3
    points=[]
    for angle in (-math.pi/2,5*math.pi/6,math.pi/6):
        angle+=base+(0 if crossing else progress*math.tau/3+settle*.018)
        radius=(33*(1-2*progress)-.42*settle if crossing else 33-10*math.sin(math.pi*progress)**2+.42*settle)/8
        points.append((radius*math.cos(angle),radius*math.sin(angle),angle+(0 if crossing else math.pi/2)))
    first,second=BUSY_PAIRS[beat%6]
    contact=smootherstep((phase-.50)/.12)*(1-smootherstep((phase-.76)/.14))
    dx,dy=points[second][0]-points[first][0],points[second][1]-points[first][1]
    move=max(0.,1-37/8/max(.001,math.hypot(dx,dy)))*contact
    x,y,angle=points[first];points[first]=(x+dx*move,y+dy*move,angle)
    bond=smootherstep((phase-.46)/.10)*(1-smootherstep((phase-.90)/.06))
    # bond[i] denotes the undirected edge i--(i+1)%3, independent of initiator.
    edge=first if second==(first+1)%3 else second
    order=(first,second,3-first-second);c,s=math.cos(turn),math.sin(turn)
    stretch=1+.032*math.sin(math.pi*progress)**2
    parts=[]
    for i,(x,y,angle) in enumerate(points):
        axis=angle+turn;ca,sa=math.cos(axis),math.sin(axis)
        parts.append(Part(8+x*c-y*s,8+x*s+y*c,radius=BUSY_RING_RADIUS,
                          mint=float(i==1),rose=float(i==2),satin=1.,
                          bond=bond if i==edge else 0.,depth=order.index(i),
                          sxx=stretch*ca*ca+sa*sa/stretch,syy=stretch*sa*sa+ca*ca/stretch,
                          sxy=(stretch-1/stretch)*ca*sa))
    return tuple(parts)


def idle_liquid_parts(elapsed):
    turn=math.tau*(max(0.,elapsed)%IDLE_ROTATION_SECONDS)/IDLE_ROTATION_SECONDS
    return tuple(Part(8+4.125*math.cos(a+turn),8+4.125*math.sin(a+turn),
                      radius=BUSY_RING_RADIUS,mint=float(i==1),rose=float(i==2),satin=1.,depth=i)
                 for i,a in enumerate((-math.pi/2,5*math.pi/6,math.pi/6)))


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
                or self.state in ('idle','busy','waiting') or self.shaking(now))

    def steady(self,now):
        elapsed=max(0.,now-self.since)
        if self.state=='busy':
            return busy_liquid_parts(elapsed)
        if self.state=='idle':
            return idle_liquid_parts(elapsed)
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
            x,y,length,radius,hole,angle,opacity,mint,bond,warm,rose,satin,sxx,syy,sxy,depth=values
            length=max(0.,length);radius=max(.05,radius)
            hole=max(0.,min(radius,hole));opacity=max(0.,min(1.,opacity))
            mint=max(0.,min(1.,mint));bond=max(0.,min(1.,bond));warm=max(0.,min(1.,warm))
            rose=max(0.,min(1.,rose));satin=max(0.,min(1.,satin))
            sxx=max(.9,min(1.1,sxx));syy=max(.9,min(1.1,syy));sxy=max(-.06,min(.06,sxy))
            # Keep every intermediate silhouette inside the fixed 16px canvas.
            radians=math.radians(angle)
            stretch=max(sxx,syy)+abs(sxy)
            rx=(abs(math.sin(radians))*length+radius)*stretch
            ry=(abs(math.cos(radians))*length+radius)*stretch
            x=max(.4+rx,min(15.6-rx,x));y=max(.4+ry,min(15.6-ry,y))
            parts.append(Part(x,y,length,radius,hole,angle,opacity,mint,bond,warm,rose,satin,sxx,syy,sxy,depth))
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
