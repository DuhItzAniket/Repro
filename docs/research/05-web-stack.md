<!-- Research notes compiled 2026-10-13 with AI-assisted web research and reviewed by the maintainers. Every claim carries a verification tag ([V]/[S]/[U]); re-verify against the primary source before citing in publications. -->

# Repro web UI: stack, rendering and replay (research pass 5)

All sources were accessed on **2026-10-13**. Versions come from the npm registry and GitHub release APIs on that day.

**Tags**
- **[V]**: the primary source was fetched and the claim seen there. This covers official docs, release notes, registry JSON, MDN/BCD JSON, caniuse JSON, W3C pages, and library source at a pinned tag.
- **[V, measured]**: a number produced on 2026-10-13 by the bundlejs.com API, which runs esbuild with `minify:true`, `treeShaking:true`, `target:esnext`, `format:esm` and gzip. These are reproducible, but Vite 8 minifies with Rolldown/Oxc, so real build output will differ by a few percent.
- **[S]**: seen only in a search snippet or a secondary source, which is named.
- **[U]**: unverified, inferred, or an engineering judgement. Every design recommendation is implicitly [U]: it is reasoning, not a fact.

No benchmark numbers (fps or ms) are given anywhere below, because no primary source with numbers for this workload was found. Section 9 says what to measure instead.

---

## 0. TL;DR

1. **Keep three.js, but use it as a thin WebGL2 host.** Use `WebGLRenderer` with `RawShaderMaterial` and instanced geometry, not `WebGPURenderer`, for M1–M8.
   - three.js is at **r186** (npm `0.186.1`, released 2026-09-24) [V].
   - The three.js manual still calls `WebGPURenderer` "in an experimental state" and says you may "encounter missing features or a better performance with `WebGLRenderer`" [V].
   - `WebGPURenderer` does not support `ShaderMaterial`, `RawShaderMaterial` or `onBeforeCompile`, so custom shaders must be TSL [V].
2. **Budget is fine.** A tree-shaken `WebGLRenderer` import is **~133 KB gzip**. three + Preact 11 + signals + d3-force together come to **~146 KB gzip** [V, measured], under half of the 300 KB budget.
   - `three/webgpu` with only `WebGPURenderer` is **~216 KB gzip** [V, measured].
3. **WebGPU in 2026 is not universal.**
   - It is missing on Firefox Linux stable and on Intel Macs in Firefox.
   - On Linux Chrome it is limited to Intel Gen12+ and NVIDIA on Wayland [V].
   - web3dsurvey reports a working adapter in 83% of reports overall and 18% on Linux (undated) [V].
4. **The workload is small for a GPU** (about 6 draw calls and under 100k vertices). The real risks are additive **fill-rate at high DPR**, **CPU work per frame**, and **GC**. They are not draw-call counts [U].
5. **Make animation pure.** Use a fold/snapshot store for state, and compute every transient visual (streak, bundle, ring snap) as `f(event, t)` from a time-window query. Scrubbing then has no accumulated animation state to rebuild [U, design].
6. **Determinism has to be designed in.**
   - d3-force uses a fixed-seed LCG [V].
   - Its initial placement uses `Math.cos`/`Math.sin`, whose precision is implementation-dependent [V].
   - So persist the computed layout instead of recomputing it per browser [U].
7. **Tooling (latest stable on npm today):**

   | Tool | Version | Released |
   |---|---|---|
   | Vite | 8.3.4 (Rolldown) | — |
   | Vitest | 5.0.4 | — |
   | Playwright | 1.64.0 | — |
   | Biome | 2.5.15 | — |
   | ESLint | 10.12.0 | — |
   | Preact | 11.0.1 | 11.0.0 on 2026-09-30 |
   | @preact/signals | 2.11.3 | — |
   | size-limit | 14.2.0 | — |
   | TypeScript | 7.0.2 | — |

   All of these are [V].
8. **Accessibility has hard requirements, all [V]:**
   - WCAG 2.2.2 (A) requires a pause control. Auto-updating content has **no 5-second exception**.
   - 2.3.1 (A) flash limits apply to the white bundles.
   - Canvas content is not exposed to assistive technology, so a parallel DOM is required.

---

## 1. three.js and alternatives

### 1.1 three.js status

**Releases** [V] (GitHub releases API):

| Release | Date |
|---|---|
| r186 | 2026-09-24 |
| r185 | 2026-07-01 |
| r184 | 2026-04-16 |
| r183 | 2026-02-20 |
| r182 | 2025-12-10 |
| r181 | 2025-11-19 |

- **npm:** `three@0.186.1`, MIT, `@types/three@0.186.0` [V].
- **Versioning:** the npm minor number tracks the r-number, so pin exact versions [U, standard practice].

**r186 notes** [V]:
- The CommonJS build is deprecated and minified builds are removed. This doesn't matter for Vite ESM.
- `PCFSoftShadowMap` is removed.
- `WebGPURenderer.dispose()` is now async.
- `Line2NodeMaterial.setupPosition()` was added.
- `compile()` on `WebGLRenderer` now supports Node Materials.

**r184** added a "NodeMaterial compatibility layer" to `WebGLRenderer` (#32851) [V]. The r186 examples list includes `webgl_tsl_instancing` [V], so TSL can partly run on `WebGLRenderer` now.

**r183** renamed `PostProcessing` to `RenderPipeline` (for WebGPURenderer) and deprecated `Clock` in favour of `Timer` [S] (app.cinevva.com news, 2026-03-18).

**WebGPURenderer** (three.js manual, r186 source of `manual/pages/webgpurenderer.html`) [V]:
- It is "the modern alternative to the long-standing `WebGLRenderer`". It falls back automatically to a WebGL 2 backend and has a `forceWebGL: true` option.
- Import from `three/webgpu`; TSL is in `three/tsl`. Initialisation is async: use `setAnimationLoop` or `await renderer.init()`.
- **Migration blockers:** "Custom materials based on `ShaderMaterial`, `RawShaderMaterial` and modifications of built-in materials via `onBeforeCompile()` are not supported." `EffectComposer` is not supported either.
- "The renderer itself is still in an experimental state … depending on your application … you will encounter missing features or a better performance with `WebGLRenderer`."
- On `WebGLRenderer`, it is "still maintained and the recommended choice for pure WebGL 2 applications", but "there are no plans to add larger new features".

**Performance comparison:** an ics.media benchmark at r176 (May 2025) found WebGLRenderer ahead in some tests, for example about 4× more separate meshes at 60 fps [S]. It is old; treat it as a reason to measure, not as a current number.

### 1.2 Bundle size (tree-shaken, gzip) [V, measured]

| Import | min (raw) | gzip |
|---|---|---|
| `three@0.186.1` `{WebGLRenderer}` only | 528 KB | **132.6 KB** |
| `three` `{WebGLRenderer, Scene, OrthographicCamera, InstancedBufferGeometry, InstancedBufferAttribute, BufferAttribute, RawShaderMaterial, Mesh, CanvasTexture}` | 530 KB | **133.2 KB** |
| `three` everything (`*`) | 742 KB | 190.7 KB |
| `three/webgpu` `{WebGPURenderer}` | 788 KB | **216.4 KB** |
| three (as row 2, plus `AdditiveBlending`, `DynamicDrawUsage`) + `preact {h,render}` + `@preact/signals {signal,computed,effect,batch}` + `d3-force {forceSimulation,forceLink,forceManyBody,forceCenter}` | 564 KB | **146.3 KB** |
| `twgl.js@7.0.0` (all) | 80 KB | 24.8 KB |
| `ogl@1.0.11` (all) | 133 KB | 39.2 KB |
| `regl@2.1.1` (all) | 123 KB | 41.5 KB |
| `pixi.js@8.22.0` (whole package, bundlephobia, not tree-shaken) | 925 KB | 264.8 KB |
| `troika-three-text@0.52.5` `{Text}`, three external | 117 KB | 43.5 KB |

- **Takeaway:** `WebGLRenderer` alone is about 99% of three's cost. The renderer pulls in the full shader-chunk library, lights and shadows, whether you use them or not [U, inferred from row 1 ≈ row 2].
- three's whole package (`*`) is only about 58 KB more than the renderer alone.
- The `ogl@1.0.11` tree-shaken query failed on bundlejs. The OGL README claims "Core 8kb, Math 6kb, Extras 15kb, Total 29kb" minzipped [V, README claim].

### 1.3 Alternatives for this workload (10k lines, 2k streaks, text-texture ring, 60 fps, < 300 KB)

| Option | Pros | Cons |
|---|---|---|
| **three.js `WebGLRenderer` + `RawShaderMaterial`** (current decision) | Already decided. 133 KB fits the budget. Mature: instancing, `CanvasTexture`/`ImageBitmap` textures, `renderer.info` counters [V source], OffscreenCanvas support (`canvas` param typed `HTMLCanvasElement \| OffscreenCanvas` [V source], `webgl_worker_offscreencanvas` example [V]). Resize, DPR and context plumbing are done. Future path to WebGPURenderer. | ~120 KB of unused code (materials, lights, shadow chunks) [U]. Scene-graph overhead is irrelevant at about 6 objects [U]. Moving to WebGPURenderer later means porting GLSL to TSL [V]. |
| **three.js `WebGPURenderer` + TSL** | Compute shaders could run the force layout on the GPU. WebGL2 fallback is built in [V]. | +83 KB gzip over WebGLRenderer [V, measured]. "Experimental" [V]. Async init. WebGPU is missing on parts of Linux and Firefox [V]. No need for compute here. |
| **twgl.js 7** | 24.8 KB [V, measured]. Thin helpers over raw WebGL2 (buffers, VAOs, uniforms). Ideal when every layer is a custom shader anyway. | We own resize, DPR, context loss and state. Smaller community. No WebGPU path. Last npm publish 2025-07-16 [V]. |
| **OGL 1.0.11** | 39 KB all-in [V, measured]. three-like API. WebGL2 first with WebGL1 fallback (`Renderer.js` tries `webgl2`) [V source]. Unlicense [V]. | Last npm publish 2025-01-27 [V]. Small team. Fewer examples. |
| **regl 2.1.1** | Functional, stateless API with "dynamic code generation" [V]. 41.5 KB [V, measured]. | WebGL1-centric: instancing "only supported if the `ANGLE_instanced_arrays` extension is available" [V, API.md]. Last npm publish 2024-11-12 [V]. |
| **PixiJS v8.22** | WebGPU and WebGL renderers. Strong 2D text and sprites [V, launch post]. | ~265 KB gzip whole package [V]. Its 2D batching model fights custom line and streak shaders [U]. Would replace the decided stack. |
| **Raw WebGL2** | 0 KB library. Maximal control. | Most code to own and test. |

**Verdict** [U]: every option can draw this scene. The deciders are bundle size, the cost of owning the code, and determinism. three.js stays because:
- it fits the budget with 150 KB to spare;
- the stack is decided, and CLAUDE.md requires asking before changing it;
- the actual render code will be ~6 custom shaders that port to twgl or raw WebGL2 in a day if the budget ever bites.

Isolate three behind a `Layer` interface (see the recommended architecture) so that swap stays cheap.

---

## 2. Rendering techniques

### 2.1 Lines (the 10k-edge dependency web)

**`LineSegments` + `LineBasicMaterial` (gl.LINES):**
- Cheapest: 2 vertices per edge, one draw call.
- `linewidth` is ignored. "WebGL and WebGPU ignore this setting and always render line primitives with a width of one pixel" [V, r186 `LineBasicMaterial.js`].
- Lines are aliased unless the context has MSAA (`antialias:true`).
- Fine for a 1px low-alpha texture. You get no control over sub-pixel weight [U].

**`LineSegments2` / `Line2` (fat lines, examples/jsm):**
- Instanced quads: `instanceStart`/`instanceEnd` live in an `InstancedInterleavedBuffer` [V source].
- `LineMaterial` is a `ShaderMaterial`. `WebGPURenderer` needs `Line2NodeMaterial` instead [V r186 notes].
- Brings raycasting and world-units code we don't need.

**Custom instanced quads (recommended)** [U]:
- One unit quad, instanced per edge. Per-instance attributes: `a`, `b`, `weight`, `lastTouchedT`.
- The vertex shader extrudes along the normal by ~1–1.5 device px. The fragment shader does analytic AA from the distance to the centre line.
- This is the technique in Rye Terrell's "Instanced Line Rendering" [V]: "pointA/pointB" per-instance attributes with a unit quad extruded by `width` along the normal.
- **Benefits:**
  - consistent sub-pixel weight with no MSAA cost;
  - per-edge alpha from recency computed **in the shader** (`uTime - lastTouchedT`), so there is no per-frame CPU work;
  - still one draw call.

**Bundles (8–20 bright curves per event):**
- One instanced mesh. Each instance is one curve segment: `(p0, ctrl, p1, curveOffset, birthT, segIndex)`.
- The vertex shader evaluates the quadratic Bézier at `segIndex/N`, offsets it along the normal by `curveOffset`, and fades by `(uTime - birthT)/1.2s`.
- Every live bundle draws in one call [U].

### 2.2 Additive blending and the "bright bundle" look

- three exposes `AdditiveBlending` (constant 2) [V source]. Use `transparent:true`, `depthTest:false`, `depthWrite:false` [U].
- Overlapping additive strokes saturate to white in an 8-bit back buffer. That *is* the reference look, so start there [U].
- **HDR accumulation (optional):**
  - Render to a half-float target and tone-map in one full-screen pass.
  - MDN WebGL best practices: "Render-to-float32 doesn't imply float32-blending!" Check `EXT_float_blend`, since "Float16-blending is always supported" [V].
  - `EXT_color_buffer_float` is in 99.95% of WebGL2 browsers tested (web3dsurvey) [V].
  - The extra full-screen pass costs fill-rate at DPR 2. Skip it unless the 8-bit look clips badly [U].
- **Avoid bloom post-processing initially.** Several full-screen passes is the most expensive thing you could add [U].

### 2.3 Motion-blurred streaks (2k live)

Instanced quads in a ring buffer of capacity N (for example 2048). Per-instance attributes [U]:
- `angle`
- `r0`
- `birthT`
- `duration`
- `speed`
- `length`
- `tintIndex`
- `intensity`

**Vertex shader** [U]:
- `age = uTime - birthT`.
- Head radius is `r0 + speed*age`.
- The tail is stretched back along the radial direction by `length * speed`. This is the fake motion blur: a velocity-stretched billboard.
- Instances with `age` outside `[0, duration]` collapse to zero area.

**Fragment shader** [U]:
- alpha = gradient along the length (bright head, transparent tail) × `1 - age/duration` × AA across the width.
- Additive blending.

**CPU uploads:**
- Write only new instances, with `BufferAttribute.addUpdateRange(start, count)` and `setUsage(DynamicDrawUsage)`. Both exist in r186 [V source].
- On a scrub, rebuild the whole buffer from the time-window query (at most 2k instances).

### 2.4 Text "file cards" ring: Canvas 2D atlas, not SDF

- **Generate in a worker.** Each card is ~20 lines of real file content drawn at 3–4 px with `OffscreenCanvasRenderingContext2D.fillText`. This works in workers on Chrome 69, Firefox 105 and Safari 16.4 [V BCD].
- **Load fonts in the worker** via `self.fonts` / `FontFace`: Chrome 69, Firefox 105, Safari 15 [V BCD].
- **Pack the atlas.** A 4096×4096 atlas is safe: web3dsurvey reports 100% of devices with WebGL2 `MAX_TEXTURE_SIZE ≥ 4096` and 86% with ≥ 16384 [V].
- **Send it to the main thread** with `transferToImageBitmap()` and transfer the `ImageBitmap` [V MDN].
- **ImageBitmap caveat in three:** for `ImageBitmap` sources, `WebGLTextures` skips `UNPACK_FLIP_Y_WEBGL` and `UNPACK_PREMULTIPLY_ALPHA_WEBGL` [V r186 source]. Flip in `createImageBitmap(..., {imageOrientation:'flipY'})` or in the UVs.
- **Draw the ring** as instanced card quads with a per-instance UV rect. Rotation and snap are uniforms computed as a pure function of `t`, so the whole ring is one draw call [U].

**SDF/MSDF (troika-three-text) is overkill here** [U]:
- At 3–4 px the glyphs are illegible by design, so SDF crispness buys nothing.
- It costs +43.5 KB gzip [V, measured].
- It generates glyph SDFs in a worker, and its supported formats are .ttf/.otf/.woff, **not .woff2** [V troika docs]. So it would need a second copy of the font.
- Cheaper still: render "pseudo-glyphs", rectangles whose width follows token length. It looks identical at 3 px [U].
- **Legible labels** (ring ticks, file paths, callouts at 8–11 px) belong in Canvas 2D or the DOM, not WebGL text [U].

### 2.5 Avoiding GC in the rAF loop

- **Why it matters:** GC pauses "can block code execution for an unpredictable length of time". A sawtooth memory graph is the symptom, and object pools / preallocation are the fix (web.dev, "Static Memory Javascript with Object Pools") [V].
- **What three.js itself does:** module-scoped scratch objects (`const _start = new Vector3()` in `LineSegments2.js`) [V source]. Copy that pattern.

**Rules** [U]:
- No closures, array literals, `map/filter`, spreads, template strings or `new` inside `frame()`.
- Instance data lives in preallocated `Float32Array`s.
- Event queries return index ranges `[lo, hi)` over typed arrays, not arrays of objects.
- Logs use a fixed-size ring buffer of preformatted strings. Strings are created on event arrival, never per frame.

**Verify** with Chrome DevTools allocation sampling, and with a Vitest test that runs `frame()` 1,000 times in Node with `--expose-gc` and asserts flat heap [U].

### 2.6 OffscreenCanvas and workers for the 2D panels

**Support** [V]:
- OffscreenCanvas is Baseline "widely available since March 2023" (MDN).
- `transferControlToOffscreen`: Chrome 69, Firefox 105, Safari 16.4 (BCD).
- `requestAnimationFrame` in dedicated workers: Chrome 69, Firefox 99, Safari 16.4 (BCD).
- caniuse: OffscreenCanvas fully supported from Safari 17 (16.2 partial: 2D only, no WebGL).

**Trade-off** [U]:
- **Gain:** moving the 8 panels to a worker isolates text-heavy 2D work from the WebGL main thread.
- **Costs:**
  1. The worker needs its own copy of the projections, either by feeding it events or by moving the EventStore into the worker.
  2. Hit-testing for clicks needs a mirrored layout on the main thread.
  3. The accessible parallel DOM must stay on the main thread anyway.
  4. Debugging is harder.

**Recommendation:** start on the main thread, but write panel renderers as pure `draw(ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, view, t)` functions with no DOM access, so they can move later if profiling shows main-thread pressure. Use workers from day one for the **heavy one-shot jobs**:
- graph layout;
- file-card atlas generation;
- log parsing for large replays.

**MDN canvas tips that apply** [V, "Optimizing canvas"]:
- layered canvases for static vs dynamic content;
- `alpha:false` where opaque;
- avoid `shadowBlur`;
- batch path calls;
- avoid floating-point coordinates;
- "Avoid text rendering whenever possible". So cache rendered log rows and blit them.

### 2.7 devicePixelRatio

- **Basic pattern** (MDN) [V]: backing store = CSS size × `devicePixelRatio`, then `ctx.scale(dpr, dpr)`. Watch for DPR changes with `matchMedia('(resolution: Xdppx)')` and re-register on change.
- **Pitfall** (MDN WebGL best practices) [V]: `canvas.width = width * devicePixelRatio` "will cause moire artifacts with non-integer values". `ResizeObserver` with `device-pixel-content-box` gives the true device-pixel size.
- **Support** (BCD) [V]: `devicePixelContentBoxSize` is in Chrome 84 and Firefox 108; **Safari: not supported**. Fall back to `Math.round(cssPx * dpr)`.
- **Fill-rate rule** [U]: clamp the stage to `min(dpr, 2)` and make the cap adaptive (drop to 1.5 when the p95 frame time exceeds budget).
- **Fill-rate arithmetic** [U, arithmetic]: a 1600×640 CSS stage at DPR 2 is ~4.1 M device pixels per full-screen additive layer. Overdraw is the real cost.

### 2.8 Other WebGL2 hygiene (MDN WebGL best practices) [V]

- Avoid `getError`/`getParameter` in the render loop: "flush + round-trip".
- Prefer `texStorage` + `texSubImage`.
- Use `KHR_parallel_shader_compile`. Check `LINK_STATUS`, and fetch compile logs only on failure.
- Use async `readPixels` via `PIXEL_PACK_BUFFER` + fence.
- On `highp`: using it unconditionally in fragment shaders "will prevent your content from working on some older mobile hardware".

---

## 3. Browser support in 2026

**WebGPU**

| Browser | Status |
|---|---|
| Chromium (Chrome, Edge) | Shipped since 113 on Windows, macOS and ChromeOS. Android 12+ on ARM, Qualcomm and Intel since 121. Linux: Intel Gen12+ since **144**, NVIDIA on Wayland (driver ≥ 535.183.01) since **147**, other hardware behind a flag. Windows ARM64 behind a flag. [V gpuweb wiki, edited 2026-10-02; BCD `GPUAdapter`] |
| Firefox | Windows since **141**. macOS Tahoe on Apple Silicon since **145**, older macOS on Apple Silicon since **147**. **No Intel Macs. No Linux in stable** (Nightly only; Mozilla "expects to ship it in 2026"). Android behind a flag. [V BCD notes; gpuweb wiki] |
| Safari | **26** on macOS, iOS, iPadOS and visionOS. caniuse marks macOS Safari "partial" because it is "only enabled by default on macOS 26 Tahoe or later". [V gpuweb wiki; caniuse JSON] |
| Real-world reach | 83% of reports return a working adapter. By platform: Windows 87.7%, macOS 90.0%, iOS 86.0%, Android 73.3%, **Linux 18.0%**. By browser: Firefox 60.1%. [V web3dsurvey, undated] |

**Other APIs** [V]:
- **WebGL 2:** supported in every current engine (caniuse: Chrome 56+, Firefox 51+, Safari 15+).
- **OffscreenCanvas:** see §2.6. Context support on OffscreenCanvas (BCD):

  | Context | Chrome | Firefox | Safari |
  |---|---|---|---|
  | `2d` | 69 | 105 | 16.4 |
  | `webgl` / `webgl2` | 69 | 105 | 17 |
  | `bitmaprenderer` | 76 | 105 | 16.4 |
  | `webgpu` | 144 | 141 | 26 |

**Vite 8's default build target** is Chrome/Edge ≥ 111, Firefox ≥ 114, Safari ≥ 16.4 ("Baseline Widely Available" as of a fixed date) [V]. That matches our API floor: OffscreenCanvas 2D and worker rAF arrive in Safari 16.4.

**Conclusion** [U]: WebGL2 is the only renderer backend that reaches 100% of a developer audience, which includes many Linux desktops. WebGPU would need a WebGL2 fallback anyway, which is exactly what WebGPURenderer does, at +83 KB.

---

## 4. Layout

**d3-force 3.0.0**: last release 2021-06-05, ISC. It is stable, not abandoned, with a small API. 5.9 KB gzip [V, measured].

**From the d3 docs** [V]:
- `forceSimulation(nodes).stop(); simulation.tick(300)` computes a static layout without the timer. "This method does not dispatch events."
- Default ticks are ⌈log(alphaMin)/log(1−alphaDecay)⌉ = **300** (alphaMin 0.001, alphaDecay ≈ 0.0228).
- `forceManyBody` uses a quadtree with Barnes–Hut, **O(n log n)** per application, `theta` default 0.9. A finite `distanceMax` "improves performance".
- **Workers:** "For large graphs, static layouts should be computed in a web worker to avoid freezing the user interface."

**Determinism** [V]:
- `randomSource` "defaults to a fixed-seed linear congruential generator". In source: `a=1664525, c=1013904223, m=2^32, s=1` (`src/lcg.js`).
- Nodes with NaN positions get a deterministic **phyllotaxis** arrangement. It uses `Math.sqrt`, `Math.cos` and `Math.sin` (`simulation.js`).
- MDN: "Many `Math` functions have a precision that's implementation-dependent … different browsers can give a different result" [V].
- **So:** same browser and same input gives an identical layout. Across engines, results may differ in the last bits and can diverge chaotically over 300 ticks [U].

**Fixes** [U]:
1. Seed initial positions yourself from a hash of the node id (integer PRNG, no trig).
2. Compute once and **persist positions keyed by graph hash**, either as a run artifact or in IndexedDB. Replay and visual tests then read stored positions.
3. Optionally let the engine compute layout in Python and emit it as data. That would be an event-schema change, so ask first.

**Alternatives:**

| Library | Version | Size (gzip) | Notes |
|---|---|---|---|
| `graphology` + `graphology-layout-forceatlas2` | 0.26.0 + 0.10.1 | 11.5 KB + 3.6 KB [V, measured] | `FA2Layout` worker supervisor (`/worker`, `start/stop/kill`). `barnesHutOptimize` defaults to **false** (O(n²)); with it on, O(n log n), `barnesHutTheta` 0.5. Positions must be pre-seeded: it "cannot be computed if all of your nodes starts with x=0 and y=0". The docs don't state determinism. [V] Good for 5k+ nodes; heavier API. [U] |
| `ngraph.forcelayout` | 3.3.1 (2022-10-04) | 9.2 KB [V, measured] | Barnes–Hut quadtree, any dimension. The README documents no random seed and no workers. [V] |
| `@cosmos.gl/graph` | 3.5.1 (2026-10-08, MIT) | — | "GPU-based force graph layout and rendering" [V npm]. GPU float maths makes cross-device determinism unlikely. It also brings its own renderer. Not recommended. [U] |
| `d3-force-3d` | 3.0.6 (2025-04) | — | Drop-in d3-force for 1D, 2D and 3D. Only useful if the web becomes 3D. [V npm] |

**Recommendation** [U]: d3-force in a module worker (`new Worker(new URL('./layout.worker.ts', import.meta.url), {type:'module'})`, the pattern from the Vite docs [V]).
- `tick(300)` with `distanceMax` set, then post back a `Float32Array` (transferable).
- If a 5k-node layout exceeds about 1 s in the M1 benchmark, switch to FA2 with `barnesHutOptimize:true`. The threshold is an engineering judgement; measure it.

---

## 5. Deterministic replay and time-travel architectures

**Event sourcing** (Fowler) [V]:
- "We can determine the application state at any point in time … starting with a blank state and rerunning the events."
- Snapshots exist because replaying from scratch is slow.
- External side effects must sit behind gateways that are disabled during replay. **For Repro:** clicking, drawer open and WS reconnect must never be driven by replayed events.

**Azure Event Sourcing pattern** (updated 2026) [V]:
- "Create snapshots at specific intervals, such as every N events … load the most recent snapshot and replay only the events that occur after it."
- "Snapshots are an optimization, not a replacement for the eventstream."
- Use versioned events with tolerant deserialisation and upcasters for schema evolution. **For Repro:** old JSONL logs must keep replaying after `packages/events` changes.

**Redux DevTools** [V]:
- `maxAge` (default **50**) caps stored history, and the docs call it "critical for performance".
- This is the price of recomputing via reducers. Repro's logs will run to thousands of events, so it needs snapshots rather than a capped history.

**Elm's time-travel debugger** replays recorded inputs through pure functions. A Hacker News thread notes that without checkpoints, stepping back from event 999 means replaying 998 events [S] (news.ycombinator.com/item?id=7863019; the elm-lang.org post did not render for the fetcher).

**Replay.io** [V]:
- Deterministic replay from the start costs time linear in recording length.
- Snapshots cost space. More snapshots mean faster seeks but more bytes.
- Their proposed fix is incremental snapshots.

**Glenn Fiedler, "Fix Your Timestep!"** [V]:
- Variable `dt` makes simulations frame-rate dependent.
- Use fixed `dt` steps fed by an accumulator, and interpolate the render state with `alpha = accumulator/dt`.
- **For Repro:** any simulated motion (for example execution-lane particles) must step on a fixed `dt` in *run time*, not wall time. Or, better, it should be closed-form in `t`.

**Synthesis for Repro** [U]: split UI state into two kinds.
- **(a) Folded state:** counters, card index, agent states, grids, log rows. A pure reducer runs over events ≤ seq, with snapshots.
- **(b) Transient visuals:** derived only from `(events whose visual window contains t, t)`. There is no stored animation state, so scrubbing costs one window query plus filling ≤ 2k instances.

Details are in the recommended architecture.

---

## 6. Tooling

| Tool | Current | Notes |
|---|---|---|
| **Vite** | 8.3.4 (2026-10-08). Vite 8 announced 2026-03-12, 8.1 on 2026-06-23 [V] | Rolldown replaces esbuild and Rollup; Oxc is the compiler; builds "up to 10-30x faster" (project claim). Needs Node 20.19+ / 22.12+ and is ESM-only. ~15 MB larger install [V]. Workers via `new Worker(new URL(...), import.meta.url)` or `?worker`; shaders via `?raw` [V]. |
| **Vitest** | 5.0.4 (2026-10-12). 5.0 announced 2026-09-03 [V] | Requires **Vite ≥ 6.4** and **Node ≥ 22.12**. `clearMocks` defaults to true. Browser Mode adds Trace View and strict locators [V]. Browser-mode `toMatchScreenshot` uses pixelmatch, has `allowedMismatchedPixelRatio`, and with the Playwright provider `animations` defaults to `"disabled"`. Its docs warn that "rendering is not perfectly deterministic across environments" and recommend generating references **in CI** [V]. |
| **Biome** | 2.5.15 (2026-09-30). v2.5 (2026-06-05): 500+ rules, cross-file linting, GritQL plugin fixes [V] | v2 (2025-06-17) added type-aware rules **without tsc**. `noFloatingPromises` caught ~75% of what typescript-eslint catches, by Biome's own limited testing [V]. One binary for lint and format. |
| **ESLint** (+ Prettier 3.9.10) | 10.12.0 (2026-10-02) [V] | v10 removed eslintrc (flat config only), needs Node ≥ 20.19 / 22.13 / 24, and looks up config from each file's directory. ESLint 9 reached EOL on 2026-08-06 [V]. |
| **Playwright** | 1.64.0 (2026-10-07) [V] | Details below. |
| **Preact** | 11.0.1. 11.0.0 released 2026-09-30, blog post 2026-09-29 [V] | "Incremental update on Preact X". Mostly type-level breaking changes; Hydration 2.0; refs forwarded by default; `Object.is` in hook deps [V]. 5.0 KB gzip (all exports) [V, measured]. |
| **@preact/signals** | 2.11.3; peer `preact >=10.25.0 \|\| >=11.0.0-0`; depends on `@preact/signals-core ^1.14.4` [V] | Passing a signal straight into JSX text binds it to the DOM text node and "updates in place without re-rendering" [V docs]. 8.4 KB gzip including the preact it imports [V, measured; inclusion U]. signals-core alone is 1.6 KB [V, measured]. |
| **size-limit** | 14.2.0 (2026-10-07) [V] | `preset-app` = `file` + `time`. Brotli by default; `gzip: true` switches to gzip. `limit: "300 kB"`. GitHub Action `andresz1/size-limit-action` comments on PRs. `time` uses headless Chrome and is "unstable" [V]. |
| **TypeScript** | 7.0.2 (2026-07-08) [V npm] | The native (Go) port per Microsoft's 2025 announcement [S]. Check typescript-eslint and Biome compatibility before adopting [U]. |

**Playwright visual regression in detail** [V]:
- `toHaveScreenshot` waits "until two consecutive page screenshots yield the same result".
- Default per-pixel `threshold` is 0.2 (YIQ). `maxDiffPixels` and `maxDiffPixelRatio` are available.
- `animations:"disabled"` stops CSS/Web Animations only. The docs say nothing about canvas or rAF, so assume it does **not** freeze a WebGL loop [U].
- `mask` paints a `#FF00FF` box by default. `scale:"css"` is the default.
- Snapshot names include browser and platform. The docs warn rendering varies with "the host OS, version, settings, hardware, power source … headless mode".
- Docker image: `mcr.microsoft.com/playwright:v1.64.0-noble` (Ubuntu 24.04).
- The Clock API (`page.clock.install`) fakes `requestAnimationFrame`, `Date` and timers. Whether `performance.now` is faked is not stated [V/U].

**WebGL determinism caveats** [V]:
- Headless Chrome disables the GPU by default (Chrome for Developers).
- Chromium's software path is **SwiftShader**. *Automatic* WebGL fallback to SwiftShader is deprecated: "WebGL context creation will soon fail instead". Opt in explicitly with `--use-angle=swiftshader` (or `--use-gl=angle --use-angle=swiftshader-webgl --enable-unsafe-swiftshader`) for testing (chromium `docs/gpu/swiftshader.md`).

**Recommendation** [U]:
- Biome for lint and format, plus `tsc --noEmit` in CI. It is one fast tool, and with no React there is little need for the ESLint plugin ecosystem. If type-aware lint gaps hurt, add typescript-eslint later, scoped.
- Pin the Node engine to ≥ 22.12, which satisfies Vite 8, Vitest 5 and ESLint 10.

---

## 7. Accessibility for animated data-viz

**WCAG 2.2.2 Pause, Stop, Hide (Level A)** [V]:
- Moving content that starts automatically, lasts more than 5 s and is shown in parallel with other content needs pause/stop/hide.
- **Auto-updating** content (our log and counters) needs pause/stop/hide or frequency control, **with no 5-second exception**.
- For real-time status, on resume "jumping to current is the better choice".
- Best practice is one control that pauses all motion.
- **For Repro** [U]: a global Pause (Space) freezes the presentation clock `t`. Ingestion continues. Resume jumps to live, or stays in replay at `t`. The pure-function design makes this trivial.

**WCAG 2.3.1 Three Flashes or Below Threshold (Level A)** [V]:
- No more than 3 general or red flashes in any 1 s, **or** concurrent flashing area within 25% of a 10° field.
- That is ≈ 341×256 px at 1024×768, or 87,296 CSS px².
- A general flash is opposing relative-luminance changes of ≥ 10% where the darker state is < 0.80.

**Risk for Repro** [U]:
- White bundles on `#080808` are large luminance changes.
- At replay **×16**, a 1.2 s run-time fade becomes 75 ms, so bursts can exceed 3 flashes/s.

**Mitigations** [U]:
1. Express visual durations in **wall-clock** ms, clamped. Keep them still pure: `f(event, t, speed)`.
2. Add a "flash governor" that caps the total bright area that can rise within any 333 ms window.
3. At ×4 and ×16, aggregate bundles (one per edge per window).

**WCAG 2.3.3 Animation from Interactions (AAA)** [V]: "Motion animation triggered by interaction can be disabled". Technique C39 is `prefers-reduced-motion`. DESIGN.md already specifies no streaks or bundles and instant state changes under reduced motion.

**`prefers-reduced-motion`** [V MDN]:
- Values are `no-preference` and `reduce`. Baseline widely available since January 2020.
- Windows 11 setting: Accessibility → Visual Effects → "Animation Effects".
- Read it with `matchMedia('(prefers-reduced-motion: reduce)')` and listen for `change` [U, standard API].
- Also offer an in-app toggle [U].

**Canvas content is not exposed to assistive technology** [V MDN]: "Canvas content is not exposed to accessibility tools as semantic HTML is". Provide fallback content inside `<canvas>`.

**Parallel DOM pattern** [U, uses V facts]:
- **Investigation feed:** mirror into a visually hidden `<div role="log" aria-label="Investigation feed">`. It has implicit `aria-live="polite"` and `aria-atomic="false"`, and the role requires an accessible name [V MDN].
- **Throttle announcements:** batch to at most one summary per ~2 s ("12 tests finished, 1 failed"), and never mirror every event [U].
- **Header counters:** real DOM text bound to signals (they are in the DOM shell anyway).
- **Card, Change×check index and evidence drawer:** semantic HTML tables and lists. The drawer is the canonical accessible view.
- **Stage canvas:** `role="img"` with a concise dynamic `aria-label` ("Dependency web: 412 modules, 37 in blast radius; focused: pkg/dates.py").
- **Panel canvases:** `aria-hidden` when their content is duplicated in the DOM.
- **Keyboard focus:** a DOM list of focusable items (claims, files, agents) drives the same `focus` action as clicks.

---

## 8. Fonts

**License** [V]:
- **JetBrains Mono** is under the **SIL Open Font License 1.1** (`OFL.txt`: "Copyright 2020 The JetBrains Mono Project Authors").
- No *Reserved Font Name* is declared after the copyright line. Subsetting and modifying are permitted, and a modified subset may keep the name.
- OFL permits use, embedding, modification and redistribution. It forbids selling the fonts by themselves (condition 1), and derivatives must stay OFL (condition 5).
- **Each copy must carry the copyright notice and the license** (condition 2), as a stand-alone text file or in the font's metadata. Ship `OFL.txt` next to the self-hosted woff2 [V].
- Latest upstream release: **v2.304** (2023-01-14).

**Self-host via Fontsource** (`@fontsource/jetbrains-mono` 5.3.0, OFL-1.1, 2026-07-19). woff2 sizes from jsDelivr metadata [V]:

| File | Bytes |
|---|---|
| latin 400 normal | 21,168 |
| latin 700 normal | 21,908 |
| latin-ext 400 | 7,336 |
| **variable** latin `wght` normal (`@fontsource-variable/jetbrains-mono` 5.3.0) | **40,404** |

**Recommendation** [U]:
- Ship the **variable latin woff2 (~40 KB)**. It is smaller than two static weights (~43 KB) and covers 700, tabular figures and in-between weights.
- Preload it, and use `font-display: block` for the shell (it is short) so Canvas 2D measurements don't use a fallback.
- Optionally subset further to ASCII with `pyftsubset` (fonttools). The saving is unmeasured.
- Load the same file in the atlas worker with `new FontFace(...)` and `self.fonts.add` [V BCD support].
- Fonts are excluded from the 300 KB JS budget per DESIGN.md.

---

## 9. Recommended UI architecture

### 9.1 Decision: keep three.js (WebGLRenderer + RawShaderMaterial, GLSL ES 3.00)

**Why:**
1. It fits: about 133 KB gzip, about 146 KB with Preact, signals and d3-force [V, measured].
2. It is the decided stack.
3. It gives OffscreenCanvas, ImageBitmap textures, `renderer.info` and instancing for free.
4. It keeps a migration path.

**Not WebGPURenderer now:**
- It is experimental [V].
- It costs +83 KB [V, measured].
- It rejects GLSL materials [V].
- WebGPU reach is 18% on Linux and absent in Firefox Linux stable [V].

**Re-evaluate** when Firefox ships WebGPU on Linux and three drops the "experimental" wording.

**Guardrail:** all GPU code sits behind a `Layer` interface, so the three.js dependency is ~200 lines of glue. Swapping to twgl.js (24.8 KB) or raw WebGL2 is possible if the budget is threatened. Record this as ADR-0002 ("Stage renderer: three.js WebGLRenderer, custom instanced layers").

### 9.2 Render layers (target: 6 stage draw calls per frame)

| # | Layer | Primitive | Per-frame CPU | Notes |
|---|---|---|---|---|
| 1 | Web edges (10k) | instanced AA quad per edge | none (uniform `uTime`) | `lastTouchedT` per edge is written on events via `addUpdateRange`. |
| 2 | Node markers | instanced points/quads | none | Blast-radius nodes only. |
| 3 | Bundles | instanced Bézier segments (curves × N segs) | fill on event / scrub | Additive. Wall-clock-clamped fade (§7). |
| 4 | Ring cards | instanced quads + 1 atlas texture (4096²) | uniforms only | Rotation and snap are a closed-form `f(t)`. |
| 5 | Ring ticks | `LineSegments` | none | Static. |
| 6 | Streaks (≤ 2k) | instanced quads, ring buffer | fill on event / scrub | Additive, gradient tail, radial stretch. |
| — | Labels / callouts | Canvas 2D overlay or DOM | on change | At most 2 callouts (DESIGN.md). |
| P | 8 panels | Canvas 2D (1 canvas or 8) | redraw only dirty panels | Pure `draw(ctx, view, t)`. |

**Renderer settings:**
- `antialias:false` (lines are self-AA'd).
- `powerPreference:'high-performance'` [V attribute exists] [U choice].
- `alpha:false`.
- `preserveDrawingBuffer` only in test mode.
- Stage DPR is adaptive and capped at 2.

### 9.3 Data flow

```
WS / JSONL ─► EventStore (append-only; columnar typed arrays + payload array; ingest validates schema v)
                 │
                 ├─► FoldedProjections (pure reducers; snapshot every N events) ─► signals (shell DOM, a11y DOM)
                 │                                                         └──► panel view-models (dirty flags)
                 └─► WindowIndex (binary search on ts) ─► TransientProjections f(event, t, speed) ─► instance buffers
Clock: t = live ? now - t0 : replayT (speed ×0.5/1/4/16, scrub, pause)   ──► frame(t) drives everything
Workers: layout.worker (d3-force) · atlas.worker (OffscreenCanvas 2D → ImageBitmap) · [later] panels.worker
```

**EventStore:**
- `seq` (Uint32Array), `tsMs` (Float64Array), `kindId`, `stageId`, `statusId` and `agentId` (Uint16Array), and `targetFileId` / `targetSymbolId` (Int32Array, interned).
- Payloads sit in a parallel JS array.
- Ingest order is `seq`. Gaps are detected and re-requested with `?from=seq`.
- Unknown kinds or fields are tolerated (upcaster table keyed by schema version) [V Azure guidance].

**FoldedProjections:**
- `apply(state, event)` is deterministic and has no I/O, no `Date.now()` and no `Math.random()`.
- Per-event randomness (curve offsets, streak jitter) comes from `hash32(event.id, salt)` → a tiny integer PRNG.
- Header counters and the Change×check footer read the **same** projection, as DESIGN.md requires.

**Snapshots:**
- Every N events (start at N = 256), `structuredClone` the folded state into a sorted array.
- Seek(t): binary search for the last snapshot ≤ seq(t), clone it, then apply forward.
- Tune N by measuring seek latency against memory, per Azure's "balance the storage cost … against the time saved" [V].
- Live mode is the same code path with `t = latest`.

**TransientProjections:**
- Query events with `ts ∈ [t − maxVisualDuration, t]`, then fill instance buffers.
- When `t` advances normally, append only new events. On a backward scrub or a jump, rebuild (≤ 2k streaks plus bundles).
- The ring snap angle is `easeOutCubic(clamp((t − tFocus)/500ms))` from the latest focus event ≤ t.

**Shell:**
- Preact 11 + signals for the header, controls, drawer and accessible DOM.
- Signals are written **once per frame at most**, with `batch()`, and only when a projection's version changed.
- The stage and panels **never** go through Preact.

### 9.4 Worker split

- **layout.worker:** d3-force `tick(300)` → transferable `Float32Array`. Results are cached by graph hash in IndexedDB, keyed by `run_id` plus graph hash, and are deterministic per stored result.
- **atlas.worker:** fetches file snippets (from engine evidence) → OffscreenCanvas 2D → `ImageBitmap` (flipY at creation).
- **Main thread:** EventStore, projections, three.js stage, panels, Preact.
- **Later option:** move panels, or the whole stage, into a worker via `transferControlToOffscreen`. three.js supports an `OffscreenCanvas` canvas, as the `webgl_worker_offscreencanvas` example shows [V]. Do this only if profiling shows main-thread contention.

### 9.5 Testing strategy (extends docs/TEST_STRATEGY.md)

1. **Projection unit and property tests (Vitest 5, Node):**
   - `fold(all) == fold(snapshot_k) + rest` for every k.
   - Scrubbing to random `t` from any start equals a linear fold.
   - Counters equal the index footer.
   - Unknown event kinds are tolerated.
2. **Render-model golden tests (no GPU):** for fixture log × `t ∈ {…}`, hash the instance `Float32Array`s and uniforms the layers would upload. This catches most "visual" regressions deterministically on Windows, Linux and CI [U, key idea].
3. **Allocation test:** run `frame(t)` 1,000× under `--expose-gc` and assert heap growth ≈ 0.
4. **Visual regression (Playwright 1.64, Chromium only):**
   - URL: `/?fixture=ref&t=12.0&paused=1&test=1`.
   - Test mode disables the rAF loop and exposes `window.__repro.renderAt(t)`, which renders exactly one frame and resolves.
   - Also call `page.clock.install()`.
   - Run in the pinned `mcr.microsoft.com/playwright:v1.64.0-noble` image with `--use-angle=swiftshader --enable-unsafe-swiftshader` (CPU-deterministic rasteriser; explicit opt-in [V]).
   - Fixed viewport, DPR 1, fonts preloaded and awaited (`document.fonts.ready`).
   - Use `maxDiffPixelRatio` around 0.001 and tune it.
   - **Baselines are generated only in CI** (Linux). Windows developers never commit baselines [V Vitest guidance; U for Playwright].
   - Use `mask` for the clock or any wall-time text.
5. **Panel component screenshots (optional):** Vitest browser mode `toMatchScreenshot` per panel `draw()` with fixture view-models.
6. **E2E:** `repro run` → WS → UI state assertions against the a11y DOM (role=log contents, counters), not pixels.
7. **Accessibility:** axe-core on the shell, drawer and a11y DOM [U, tool not researched here]. Unit test the flash governor: at ×16 on the burst fixture, no 333 ms window exceeds the area threshold.

### 9.6 Performance instrumentation

**In-app HUD** (toggle with a key; compiled out of prod or lazy-loaded) [U]:
- Rolling frame-time p50/p95/p99 from rAF deltas in a preallocated ring buffer.
- `renderer.info.render.calls/triangles/lines` [V source] to assert ≤ 6 stage calls.
- Live instance counts.
- Snapshot-seek ms.
- Event ingest rate.

**GPU timing:** `EXT_disjoint_timer_query_webgl2` is Chrome 70+ only; Firefox and Safari don't have it [V BCD]. Use it as a dev aid only.

**Long Animation Frames API** (`PerformanceLongAnimationFrameTiming`): Chrome 123+ only [V BCD]. Use it in perf CI to attribute jank.

**CI gates:**
- size-limit `gzip:true`, `limit:"300 kB"` on every PR [V tool].
- Nightly Playwright perf run on a stress fixture (10k edges, 2k streaks, ×16 replay) that records frame-time percentiles and LoAF counts. Gate on **relative regression** against the previous nightly, since CI GPUs are not "a mid laptop" [U].
- Keep a manual checklist run on a real mid laptop (Windows, integrated GPU) at each milestone gate [U].

### 9.7 Open questions for the user (CLAUDE.md rule 7)

1. **Persisting the computed layout:** do it as an engine artifact or a `graph.layout` event (schema change), or only as a client-side cache?
2. **Wall-clock-clamped durations at ×4/×16:** these are needed for WCAG 2.3.1. Changing DESIGN.md's motion durations needs sign-off.
3. **Biome instead of ESLint+Prettier:** this is a tooling choice within the stack, but confirm it.

---

## Sources (all accessed 2026-10-13)

| # | URL | Tag |
|---|---|---|
| 1 | https://github.com/mrdoob/three.js/releases and https://api.github.com/repos/mrdoob/three.js/releases | V |
| 2 | https://github.com/mrdoob/three.js/releases/tag/r186 | V |
| 3 | https://github.com/mrdoob/three.js/releases/tag/r184 | V |
| 4 | https://raw.githubusercontent.com/mrdoob/three.js/r186/manual/pages/webgpurenderer.html | V |
| 5 | https://raw.githubusercontent.com/mrdoob/three.js/r186/src/materials/LineBasicMaterial.js | V |
| 6 | https://raw.githubusercontent.com/mrdoob/three.js/r186/examples/jsm/lines/LineSegments2.js | V |
| 7 | https://raw.githubusercontent.com/mrdoob/three.js/r186/src/core/BufferAttribute.js and `src/constants.js` | V |
| 8 | https://raw.githubusercontent.com/mrdoob/three.js/r186/src/renderers/webgl/WebGLTextures.js | V |
| 9 | https://raw.githubusercontent.com/mrdoob/three.js/r186/src/renderers/webgl/WebGLInfo.js and `src/renderers/WebGLRenderer.js` | V |
| 10 | https://raw.githubusercontent.com/mrdoob/three.js/r186/examples/files.json | V |
| 11 | https://registry.npmjs.org/ (three, regl, ogl, twgl.js, pixi.js, d3-force, d3-force-3d, graphology, graphology-layout-forceatlas2, ngraph.forcelayout, vite, vitest, @biomejs/biome, eslint, prettier, @playwright/test, preact, @preact/signals, @preact/signals-core, size-limit, troika-three-text, @fontsource/jetbrains-mono, @fontsource-variable/jetbrains-mono, typescript, @types/three, @cosmos.gl/graph, sigma) | V |
| 12 | https://deno.bundlejs.com/ (API queries listed in §1.2) | V, measured |
| 13 | https://bundlephobia.com/api/size?package=pixi.js@8.22.0 | V |
| 14 | https://ics.media/en/entry/250501/ (WebGPU vs WebGL benchmark at r176) | S |
| 15 | https://app.cinevva.com/tr/news/2026-03-18-threejs-r183-render-pipeline | S |
| 16 | https://github.com/oframe/ogl and https://raw.githubusercontent.com/oframe/ogl/master/src/core/Renderer.js | V |
| 17 | https://github.com/regl-project/regl and https://raw.githubusercontent.com/regl-project/regl/gh-pages/API.md | V |
| 18 | https://pixijs.com/blog/pixi-v8-launches | V |
| 19 | https://protectwise.github.io/troika/troika-three-text/ | V |
| 20 | https://wwwtyro.net/2019/11/18/instanced-lines.html | V |
| 21 | https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/WebGL_best_practices | V |
| 22 | https://developer.mozilla.org/en-US/docs/Web/API/Canvas_API/Tutorial/Optimizing_canvas | V |
| 23 | https://developer.mozilla.org/en-US/docs/Web/API/Window/devicePixelRatio | V |
| 24 | https://web.dev/articles/device-pixel-content-box | V |
| 25 | https://web.dev/articles/speed-static-mem-pools | V |
| 26 | https://developer.mozilla.org/en-US/docs/Web/API/OffscreenCanvas | V |
| 27 | https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/canvas | V |
| 28 | https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/getContext | V |
| 29 | https://raw.githubusercontent.com/Fyrd/caniuse/main/features-json/webgpu.json, `offscreencanvas.json`, `webgl2.json` (data updated 2026-10-13) | V |
| 30 | https://github.com/gpuweb/gpuweb/wiki/Implementation-Status (edited 2026-10-02) | V |
| 31 | https://raw.githubusercontent.com/mdn/browser-compat-data/main/api/ (GPUAdapter, OffscreenCanvas, ResizeObserverEntry, DedicatedWorkerGlobalScope, WorkerGlobalScope, FontFace, HTMLCanvasElement, OffscreenCanvasRenderingContext2D, EXT_disjoint_timer_query_webgl2, PerformanceLongAnimationFrameTiming).json | V |
| 32 | https://web3dsurvey.com/webgpu, https://web3dsurvey.com/webgl2/parameters/MAX_TEXTURE_SIZE, https://web3dsurvey.com/webgl2/extensions/EXT_color_buffer_float | V (undated data) |
| 33 | https://d3js.org/d3-force/simulation and https://d3js.org/d3-force/many-body | V |
| 34 | https://raw.githubusercontent.com/d3/d3-force/main/src/lcg.js and `src/simulation.js` | V |
| 35 | https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Math | V |
| 36 | https://graphology.github.io/standard-library/layout-forceatlas2.html | V |
| 37 | https://github.com/anvaka/ngraph.forcelayout | V |
| 38 | https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing | V |
| 39 | https://martinfowler.com/eaaDev/EventSourcing.html | V |
| 40 | https://github.com/reduxjs/redux-devtools/blob/main/extension/docs/API/Arguments.md | V |
| 41 | https://gafferongames.com/post/fix_your_timestep/ | V |
| 42 | https://www.replay.io/blog/how-to-build-a-time-machine | V |
| 43 | https://news.ycombinator.com/item?id=7863019 (Elm debugger replay discussion, via search snippet) | S |
| 44 | https://elm-lang.org/news/time-travel-made-easy (fetch returned no body) | S |
| 45 | https://vite.dev/blog/, https://vite.dev/blog/announcing-vite8, https://vite.dev/guide/features, https://vite.dev/guide/build | V |
| 46 | https://vitest.dev/blog/, https://vitest.dev/blog/vitest-5, https://vitest.dev/guide/browser/visual-regression-testing | V |
| 47 | https://biomejs.dev/blog/, https://biomejs.dev/blog/biome-v2/, https://biomejs.dev/blog/biome-v2-5/ | V |
| 48 | https://eslint.org/blog/ and https://eslint.org/docs/latest/use/migrate-to-10.0.0 | V |
| 49 | https://playwright.dev/docs/test-snapshots, https://playwright.dev/docs/api/class-pageassertions, https://playwright.dev/docs/docker, https://playwright.dev/docs/api/class-clock | V |
| 50 | https://chromium.googlesource.com/chromium/src/+/main/docs/gpu/swiftshader.md | V |
| 51 | https://developer.chrome.com/blog/supercharge-web-ai-testing | V |
| 52 | https://preactjs.com/guide/v11/signals, https://preactjs.com/blog/preact-11, https://github.com/preactjs/preact/releases/tag/11.0.0 | V |
| 53 | https://github.com/ai/size-limit | V |
| 54 | https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html | V |
| 55 | https://www.w3.org/WAI/WCAG22/Understanding/three-flashes-or-below-threshold.html | V |
| 56 | https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html | V |
| 57 | https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion | V |
| 58 | https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Roles/log_role | V |
| 59 | https://raw.githubusercontent.com/JetBrains/JetBrainsMono/master/OFL.txt and https://api.github.com/repos/JetBrains/JetBrainsMono/releases/latest | V |
| 60 | https://data.jsdelivr.com/v1/packages/npm/@fontsource/jetbrains-mono@5.3.0 and `@fontsource-variable/jetbrains-mono@5.3.0` (file sizes) | V |
| 61 | TypeScript native-port announcement (Microsoft devblogs, 2025); not fetched this session | S |

**Gaps**
- The shared web-search budget ran out mid-session. Everything after that point used direct fetches of known primary URLs.
- No primary-source fps benchmark exists for this exact workload. M1 should include a stress-fixture spike (10k edges, 2k streaks, ring, DPR 2, ×16) on a mid laptop before locking parameters.
- d3-force timing for 1–5k nodes is unmeasured.
- The bundle size of TSL running on `WebGLRenderer` is unmeasured.
