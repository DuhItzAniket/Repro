/**
 * The WebGL host: the only module that imports three.js (ADR-0008 keeps three behind this
 * glue, so it can be swapped for raw WebGL2 if the budget demands). It owns the renderer and
 * one instanced mesh per layer, runs `update → upload → draw` each frame, adapts the device
 * pixel ratio, and keeps frame statistics for the perf HUD.
 */
import {
  AdditiveBlending,
  BufferAttribute,
  DataTexture,
  DoubleSide,
  DynamicDrawUsage,
  GLSL3,
  InstancedBufferAttribute,
  InstancedBufferGeometry,
  LinearFilter,
  Mesh,
  NormalBlending,
  OrthographicCamera,
  RawShaderMaterial,
  Scene,
  Texture,
  WebGLRenderer,
} from "three";
import type { Ring } from "../shell/layout";
import { AdaptiveDpr } from "./dpr";
import type { InstanceBuffers } from "./instances";
import type { StageFrame, StageLayer } from "./layer";
import type { CardLayer } from "./ring/layers";
import { NO_RECENCY } from "./segments";
import cardFrag from "./shaders/card.frag.glsl?raw";
import cardVert from "./shaders/card.vert.glsl?raw";
import segmentFrag from "./shaders/segment.frag.glsl?raw";
import segmentVert from "./shaders/segment.vert.glsl?raw";
import { FrameStats } from "./stats";

export interface StageInfo {
  /** The GPU that WebGL reports (unmasked when the browser allows it). */
  readonly gpu: string;
  dpr: number;
  drawCalls: number;
  triangles: number;
  /** Instances drawn last frame, per layer. */
  readonly instances: Record<string, number>;
}

interface Binding {
  readonly layer: StageLayer;
  readonly mesh: Mesh<InstancedBufferGeometry, RawShaderMaterial>;
  generation: number;
  version: number;
  /** Card layers: the atlas version currently bound as a texture. */
  atlasVersion: number;
  texture: Texture | null;
}

const isCardLayer = (layer: StageLayer): layer is CardLayer => layer.primitive === "cards";

/** A 1×1 transparent texture, bound until a card atlas arrives. */
function emptyTexture(): Texture {
  const texture = new DataTexture(new Uint8Array(4), 1, 1);
  texture.needsUpdate = true;
  return texture;
}

type MutableFrame = { -readonly [K in keyof StageFrame]: StageFrame[K] };

const QUAD_CORNERS = new Float32Array([0, -1, 1, -1, 0, 1, 1, 1]);
const QUAD_INDEX = [0, 1, 2, 2, 1, 3];

function readGpu(renderer: WebGLRenderer): string {
  const gl = renderer.getContext();
  const debug = gl.getExtension("WEBGL_debug_renderer_info");
  const name =
    debug === null ? gl.getParameter(gl.RENDERER) : gl.getParameter(debug.UNMASKED_RENDERER_WEBGL);
  return String(name);
}

export interface StageHostOptions {
  readonly devicePixelRatio: number;
  /** Fixed DPR (benchmarks); adaptive when omitted. */
  readonly fixedDpr?: number;
  /** Clock for CPU timing (defaults to `performance.now`). */
  readonly clock?: () => number;
}

export class StageHost {
  readonly stats = new FrameStats();
  readonly info: StageInfo;
  private readonly renderer: WebGLRenderer;
  private readonly scene = new Scene();
  // Raw shaders project themselves; three still needs a camera to call render().
  private readonly camera = new OrthographicCamera();
  private readonly bindings: Binding[] = [];
  private readonly adaptive: AdaptiveDpr | null;
  private readonly now: () => number;
  private readonly viewport = [1, 1];
  /** Ring centre and radius, shared by card materials. */
  private readonly center = [0, 0];
  private readonly radius = { value: 1 };
  /** Shared by every layer's material: presentation time in ms. */
  private readonly time = { value: 0 };
  private readonly input: MutableFrame;
  private dpr: number;
  private lastStart = Number.NaN;

  constructor(
    readonly canvas: HTMLCanvasElement,
    options: StageHostOptions,
  ) {
    this.renderer = new WebGLRenderer({
      canvas,
      antialias: false, // segments anti-alias themselves; MSAA would only cost fill rate
      alpha: false,
      powerPreference: "high-performance",
    });
    this.renderer.setClearColor(0x080808, 1);
    this.adaptive =
      options.fixedDpr === undefined ? new AdaptiveDpr({ device: options.devicePixelRatio }) : null;
    this.dpr = options.fixedDpr ?? this.adaptive?.dpr ?? 1;
    this.now = options.clock ?? (() => performance.now());
    this.info = {
      gpu: readGpu(this.renderer),
      dpr: this.dpr,
      drawCalls: 0,
      triangles: 0,
      instances: {},
    };
    this.input = { t: 0, cursor: 0, width: 1, height: 1, ring: { cx: 0, cy: 0, r: 1 } };
  }

  add(layer: StageLayer): void {
    const material = isCardLayer(layer) ? this.cardMaterial() : this.segmentMaterial(layer);
    const mesh = new Mesh(geometryFor(layer.buffers), material);
    mesh.frustumCulled = false;
    // Layers draw in the order they were added: the web, then the ring over it, then streaks.
    mesh.renderOrder = this.bindings.length;
    const binding: Binding = {
      layer,
      mesh,
      generation: layer.buffers.generation,
      version: -1,
      atlasVersion: -1,
      texture: null,
    };
    this.bindings.push(binding);
    this.scene.add(mesh);
    this.info.instances[layer.name] = 0;
  }

  private segmentMaterial(layer: StageLayer): RawShaderMaterial {
    const recency = layer.recency ?? NO_RECENCY;
    return new RawShaderMaterial({
      glslVersion: GLSL3,
      vertexShader: segmentVert,
      fragmentShader: segmentFrag,
      uniforms: {
        uViewport: { value: this.viewport },
        uDpr: { value: this.dpr },
        uTime: this.time,
        uFlare: { value: recency.flare },
        uFlareMs: { value: recency.flareMs },
        uCenter: { value: this.center },
        uSpin: { value: [1, 0] },
      },
      blending: AdditiveBlending,
      transparent: true,
      depthTest: false,
      depthWrite: false,
      // The shader maps y-down stage pixels to y-up clip space, which reverses the winding,
      // and a segment's quad winding also depends on its direction. Never cull: with three's
      // default FrontSide every segment was culled and nothing was drawn.
      side: DoubleSide,
    });
  }

  private cardMaterial(): RawShaderMaterial {
    return new RawShaderMaterial({
      glslVersion: GLSL3,
      vertexShader: cardVert,
      fragmentShader: cardFrag,
      uniforms: {
        uViewport: { value: this.viewport },
        uCenter: { value: this.center },
        uRadius: this.radius,
        uRotation: { value: 0 },
        uTime: this.time,
        uAtlas: { value: emptyTexture() },
      },
      // The band is opaque: it hides the web behind it, like the reference.
      blending: NormalBlending,
      transparent: true,
      depthTest: false,
      depthWrite: false,
      side: DoubleSide,
    });
  }

  /**
   * Rebinds a layer whose buffers were reallocated. A new geometry, not new attributes on the
   * old one: three.js caches the maximum instance count per geometry from the first arrays it
   * saw, and would silently draw no more instances than that (found in B05).
   */
  private attach(binding: Binding): void {
    const old = binding.mesh.geometry;
    binding.mesh.geometry = geometryFor(binding.layer.buffers);
    old.dispose();
    binding.generation = binding.layer.buffers.generation;
    binding.version = -1;
  }

  /** Sizes the drawing buffer for a stage of `width × height` CSS pixels and sets its ring. */
  resize(width: number, height: number, ring: Ring): void {
    this.input.width = Math.max(1, width);
    this.input.height = Math.max(1, height);
    this.input.ring = ring;
    this.center[0] = ring.cx;
    this.center[1] = ring.cy;
    this.radius.value = ring.r;
    this.applySize();
  }

  private applySize(): void {
    this.renderer.setPixelRatio(this.dpr);
    this.renderer.setSize(this.input.width, this.input.height, true);
    this.viewport[0] = this.input.width;
    this.viewport[1] = this.input.height;
    for (const { mesh } of this.bindings) {
      const uniform = mesh.material.uniforms.uDpr;
      if (uniform !== undefined) uniform.value = this.dpr;
    }
    this.info.dpr = this.dpr;
  }

  /** One frame: layers write instances, the host uploads what changed and draws. */
  frame(t: number, cursor: number): void {
    const start = this.now();
    this.input.t = t;
    this.input.cursor = cursor;
    this.time.value = t;
    for (const binding of this.bindings) {
      const { layer } = binding;
      layer.update(this.input);
      if (binding.generation !== layer.buffers.generation) this.attach(binding);
      if (binding.version !== layer.buffers.version) {
        upload(binding.mesh.geometry, layer.buffers);
        binding.version = layer.buffers.version;
      }
      if (layer.rotation !== undefined) this.spin(binding, layer.rotation);
      if (isCardLayer(layer)) this.bindCards(binding, layer);
      this.info.instances[layer.name] = layer.buffers.count;
    }
    this.renderer.render(this.scene, this.camera);
    this.stats.record(start, this.now() - start);
    this.info.drawCalls = this.renderer.info.render.calls;
    this.info.triangles = this.renderer.info.render.triangles;
    if (this.adaptive !== null && !Number.isNaN(this.lastStart)) {
      if (this.adaptive.sample(start - this.lastStart) && this.adaptive.dpr !== this.dpr) {
        this.dpr = this.adaptive.dpr;
        this.applySize();
      }
    }
    this.lastStart = start;
  }

  /** Sets a turning layer's rotation uniform (cards: an angle; segments: its cos and sin). */
  private spin(binding: Binding, rotation: number): void {
    const uniforms = binding.mesh.material.uniforms;
    const angle = uniforms.uRotation;
    if (angle !== undefined) angle.value = rotation;
    const spin = uniforms.uSpin?.value as number[] | undefined;
    if (spin !== undefined) {
      spin[0] = Math.cos(rotation);
      spin[1] = Math.sin(rotation);
    }
  }

  private bindCards(binding: Binding, layer: CardLayer): void {
    const uniforms = binding.mesh.material.uniforms;
    const { bitmap, version } = layer.atlas;
    if (version === binding.atlasVersion || bitmap === null) return;
    binding.atlasVersion = version;
    const texture = new Texture(bitmap);
    texture.flipY = false; // ImageBitmaps cannot be flipped on upload; the atlas uses v = 0 at the top
    texture.generateMipmaps = false;
    texture.minFilter = LinearFilter;
    texture.magFilter = LinearFilter;
    texture.needsUpdate = true;
    binding.texture?.dispose();
    binding.texture = texture;
    const atlas = uniforms.uAtlas;
    if (atlas !== undefined) atlas.value = texture;
  }

  /**
   * Renders the current frame again and counts pixels brighter than the background. It reads
   * the whole drawing buffer back, so it is for benchmarks and debugging only, never per frame.
   * The benchmark refuses to report timings for a stage that draws nothing.
   */
  probeLitPixels(): number {
    this.renderer.render(this.scene, this.camera);
    const gl = this.renderer.getContext();
    const width = gl.drawingBufferWidth;
    const height = gl.drawingBufferHeight;
    const pixels = new Uint8Array(width * height * 4);
    gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    let lit = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      // The clear colour is #080808.
      if (
        (pixels[i] as number) > 8 ||
        (pixels[i + 1] as number) > 8 ||
        (pixels[i + 2] as number) > 8
      )
        lit++;
    }
    return lit;
  }

  dispose(): void {
    for (const { mesh, texture } of this.bindings) {
      mesh.geometry.dispose();
      mesh.material.dispose();
      texture?.dispose();
    }
    this.renderer.dispose();
  }
}

function geometryFor(buffers: InstanceBuffers): InstancedBufferGeometry {
  const geometry = new InstancedBufferGeometry();
  geometry.setAttribute("corner", new BufferAttribute(QUAD_CORNERS, 2));
  geometry.setIndex(QUAD_INDEX);
  for (const spec of buffers.specs) {
    const attribute = new InstancedBufferAttribute(buffers.array(spec.name), spec.size);
    attribute.setUsage(DynamicDrawUsage);
    geometry.setAttribute(spec.name, attribute);
  }
  return geometry;
}

function upload(geometry: InstancedBufferGeometry, buffers: InstanceBuffers): void {
  geometry.instanceCount = buffers.count;
  if (buffers.count === 0) return;
  for (const spec of buffers.specs) {
    const attribute = geometry.getAttribute(spec.name) as InstancedBufferAttribute;
    attribute.clearUpdateRanges();
    attribute.addUpdateRange(0, buffers.count * spec.size);
    attribute.needsUpdate = true;
  }
}
