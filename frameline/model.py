"""Project model: library, timeline clips, markers, annotations (with undo)."""
import copy


class Clip:
    _ids = 0

    def __init__(self, source, start=0, length=None):
        Clip._ids += 1
        self.id = Clip._ids
        self.source = source
        self.start = start
        self._length = length

    @property
    def length(self):
        if self._length:
            return self._length
        if self.source.kind == "image":
            return 24
        return max(1, self.source.frames - self.start)

    @length.setter
    def length(self, v):
        self._length = max(1, int(v))

    def local(self, offset):
        if self.source.kind == "image":
            return 0
        return self.source.clamp(self.start + offset)

    def to_dict(self):
        return {"path": self.source.path, "start": self.start, "length": self._length}


class Project:
    def __init__(self):
        self.sources = []
        self.clips = []
        self.markers = {}          # global frame -> {"color": str, "note": str}
        self.annotations = {}      # "path|localframe" -> [stroke dict]
        self.fps_override = None
        self.undo_stack = []
        self.redo_stack = []
        self.path = None
        self.dirty = False

    # ---- timeline
    @property
    def fps(self):
        if self.fps_override:
            return self.fps_override
        if self.clips:
            return self.clips[0].source.fps
        return 24.0

    def total(self):
        return sum(c.length for c in self.clips)

    def starts(self):
        out, s = [], 0
        for c in self.clips:
            out.append(s)
            s += c.length
        return out

    def locate(self, g):
        s = 0
        for c in self.clips:
            if g < s + c.length:
                return c, max(0, g - s), s
            s += c.length
        if self.clips:
            c = self.clips[-1]
            return c, c.length - 1, s - c.length
        return None, 0, 0

    def clip_index_at(self, g):
        s = 0
        for i, c in enumerate(self.clips):
            if g < s + c.length:
                return i
            s += c.length
        return len(self.clips) - 1

    # ---- annotations
    @staticmethod
    def akey(source, local):
        return f"{source.path}|{local}"

    def strokes(self, source, local):
        return self.annotations.get(self.akey(source, local), [])

    def set_strokes(self, source, local, strokes, record=True):
        k = self.akey(source, local)
        if record:
            self.undo_stack.append((k, copy.deepcopy(self.annotations.get(k, []))))
            self.redo_stack.clear()
        if strokes:
            self.annotations[k] = strokes
        else:
            self.annotations.pop(k, None)
        self.dirty = True

    def add_stroke(self, source, local, stroke):
        self.set_strokes(source, local, self.strokes(source, local) + [stroke])

    def undo(self):
        if not self.undo_stack:
            return None
        k, before = self.undo_stack.pop()
        self.redo_stack.append((k, copy.deepcopy(self.annotations.get(k, []))))
        self._apply(k, before)
        return k

    def redo(self):
        if not self.redo_stack:
            return None
        k, after = self.redo_stack.pop()
        self.undo_stack.append((k, copy.deepcopy(self.annotations.get(k, []))))
        self._apply(k, after)
        return k

    def _apply(self, k, strokes):
        if strokes:
            self.annotations[k] = strokes
        else:
            self.annotations.pop(k, None)
        self.dirty = True

    def annotated_globals(self):
        """Global frames (on the timeline) that carry annotations."""
        res = []
        s = 0
        for c in self.clips:
            prefix = c.source.path + "|"
            for k in self.annotations:
                if k.startswith(prefix):
                    lf = int(k[len(prefix):])
                    if c.source.kind == "image":
                        res.append(s)
                    elif c.start <= lf < c.start + c.length:
                        res.append(s + lf - c.start)
            s += c.length
        return sorted(set(res))
