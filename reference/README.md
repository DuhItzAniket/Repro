# Visual reference

The cockpit's visual language is modelled on a third-party screen recording (the "Paper Lab"
demo: a multi-agent Claude Code project that turned research papers into runnable experiments).

The media itself is **not committed to this repository**. We did not create it and do not have
the right to redistribute it. Contributors who have a local copy keep it at:

```
reference/paper-lab-reference.mp4   22 s loop, portrait 1280x1600
reference/frames/frame_{1,6,12,18}s.png
reference/panels/{header,stage,panel_1..panel_8}.png
```

These paths are listed in `.gitignore`.

Everything the implementation needs from the reference is written down in
[`docs/DESIGN.md`](../docs/DESIGN.md): layout, palette (sampled values), type scale, the
behaviour of every panel and the motion rules. The design doc is the spec. The video is only an
aid for whoever implements Stage B.
