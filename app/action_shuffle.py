"""Visit each available action once per randomized round."""
import random


class ActionShuffle:
    def __init__(self):
        self.pool=frozenset()
        self.remaining=[]
        self.last=None

    def next(self,items):
        by_file={item.get('playbackFile') or item['file']:item for item in items}
        pool=frozenset(by_file)
        if pool!=self.pool:
            self.pool=pool
            self.remaining=[]
        if not by_file:return None
        if not self.remaining:
            self.remaining=list(by_file)
            random.shuffle(self.remaining)
            # pop() consumes the end; avoid a repeat across round boundaries.
            if len(self.remaining)>1 and self.remaining[-1]==self.last:
                other=random.randrange(len(self.remaining)-1)
                self.remaining[-1],self.remaining[other]=self.remaining[other],self.remaining[-1]
        self.last=self.remaining.pop()
        return by_file[self.last]
