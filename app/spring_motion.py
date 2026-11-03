"""Bounded snapshot motion, tuned against Apple's WWDC23 island examples."""
import math

EXPAND_MS = 480
SHRINK_MS = 440
DISMISS_MS = 360


def expand_progress(value):
    t = max(0., min(1., float(value)))
    return 4. * t ** 3 if t < .5 else 1. - (-2. * t + 2.) ** 3 / 2.


def island_response(value):
    """A damped response with zero initial velocity and a small overshoot.

    These are our adaptation parameters, not Apple's unpublished constants.
    Settle before the handoff, avoiding a second one-pixel oscillation.
    """
    t=max(0.,min(1.,float(value)))
    response=1.-math.exp(-8.5*t)*(math.cos(6.5*t)+8.5/6.5*math.sin(6.5*t))
    if t>=.82:return 1.
    settle=stage(t,.58,.82)
    return response+(1.-response)*settle


def stage(value,start,end):
    t=max(0.,min(1.,(float(value)-start)/(end-start)))
    return t*t*(3.-2.*t)


def container_progress(value):
    """Bounded asymmetric ease with zero velocity and acceleration at both ends.

    The beta(3, 5) integral starts gently, then leaves more time for settling.
    Preserve the final tenth for the existing exact-pixel raster handoff.
    """
    t=max(0.,min(1.,float(value)))
    if t>=.9:return 1.
    u=t/.9
    if u>=.5:return 1.-(1.-u)**5*(1.+5.*u+15.*u*u)
    return max(0.,min(1.,u*u*u*(35.+u*(-105.+u*(126.+u*(-70.+15.*u))))))


def dismiss_progress(value):
    """A small initial anticipation, then one uninterrupted disappearance."""
    t = max(0., min(1., float(value)))
    if t<.12:return -.006*stage(t,0.,.12)
    return -.006+1.006*stage(t,.12,1.)
