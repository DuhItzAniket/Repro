# ADR-0008: Stage renderer — three.js WebGLRenderer with custom instanced layers

- **Status:** accepted (refines the decided stack)
- **Date:** 2026-10-13
- **Phase:** A01 (implemented in B04–B07)

## Context
The stage draws about 10k thin edges, transient bundles, a ring of text-texture cards and up
to 2k motion-blurred streaks at 60 fps, within a 300 KB gzipped JS budget. Facts verified on
2026-10-13 (research/05 §1–3):
- three.js r186 (`0.186.1`). The manual calls `WebGPURenderer` "still in an experimental
  state". It rejects `ShaderMaterial`/`RawShaderMaterial` (custom shaders must be TSL) and adds
  about 83 KB gzip.
- A tree-shaken `WebGLRenderer` import is about 133 KB gzip. three + Preact 11 + signals +
  d3-force is about 146 KB.
- WebGPU reaches about 18% of Linux reports and is absent from Firefox stable on Linux.
- WebGL line primitives are always 1px.

## Decision
- three.js `WebGLRenderer` with `RawShaderMaterial` (GLSL ES 3.00). Six instanced layers: edges
  as anti-aliased quads, node markers, Bézier bundles, ring cards from a Canvas-2D atlas, ring
  ticks, and streaks from a ring buffer. Additive blending, no post-processing.
- All GPU code sits behind a `Layer` interface, so three.js is about 200 lines of glue and can
  be swapped for twgl.js or raw WebGL2 if the budget is threatened.
- No SDF text. At 3–4px the card text is texture, not reading material.
- Revisit WebGPU when Firefox ships it on Linux and three.js drops the "experimental" label.

## Consequences
Shaders are hand-written GLSL. Porting to WebGPU later means rewriting them in TSL. Render
correctness is tested GPU-free by hashing the instance buffers each layer uploads, plus
Playwright screenshots under SwiftShader in CI.
