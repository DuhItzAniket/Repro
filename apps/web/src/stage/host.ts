/**
 * The WebGL host: the only module that imports three.js (ADR-0008 keeps three behind this
 * glue, so it can be swapped for raw WebGL2 if the budget demands). It owns the renderer and
 * one instanced mesh per layer, runs `update → upload → draw` each frame, adapts the device
 * pixel ratio, and keeps frame statistics for the perf HUD.
 */
import {
  AdditiveBlending,
  BufferAttribute,
  DynamicDrawUsage,
  GLSL3,
  InstancedBufferAttribute,
  InstancedBufferGeometry,
  Mesh,
  OrthographicCamera,
  RawShaderMaterial,
  Scene,
  WebGLRenderer,
} from "three";
import type { Ring } from "../shell/layout";
import { AdaptiveDpr } from "./dpr";
import type { InstanceBuffers } from "./instances";
import type { StageFrame, StageLayer } from "./layer";
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
    const material = new RawShaderMaterial({
      glslVersion: GLSL3,
      vertexShader: segmentVert,
      fragmentShader: segmentFrag,
      uniforms: { uViewport: { value: this.viewport }, uDpr: { value: this.dpr } },
      blending: AdditiveBlending,
      transparent: true,
      depthTest: false,
      depthWrite: false,
    });
    const geometry = new InstancedBufferGeometry();
    geometry.setAttribute("corner", new BufferAttribute(QUAD_CORNERS, 2));
    geometry.setIndex(QUAD_INDEX);
    const mesh = new Mesh(geometry, material);
    mesh.frustumCulled = false;
    const binding: Binding = { layer, mesh, generation: -1, version: -1 };
    this.attach(binding);
    this.bindings.push(binding);
    this.scene.add(mesh);
    this.info.instances[layer.name] = 0;
  }

  private attach(binding: Binding): void {
    const { buffers } = binding.layer;
    for (const spec of buffers.specs) {
      const attribute = new InstancedBufferAttribute(buffers.array(spec.name), spec.size);
      attribute.setUsage(DynamicDrawUsage);
      binding.mesh.geometry.setAttribute(spec.name, attribute);
    }
    binding.generation = buffers.generation;
    binding.version = -1;
  }

  /** Sizes the drawing buffer for a stage of `width × height` CSS pixels and sets its ring. */
  resize(width: number, height: number, ring: Ring): void {
    this.input.width = Math.max(1, width);
    this.input.height = Math.max(1, height);
    this.input.ring = ring;
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
    for (const binding of this.bindings) {
      const { layer } = binding;
      layer.update(this.input);
      if (binding.generation !== layer.buffers.generation) this.attach(binding);
      if (binding.version !== layer.buffers.version) {
        upload(binding.mesh.geometry, layer.buffers);
        binding.version = layer.buffers.version;
      }
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

  dispose(): void {
    for (const { mesh } of this.bindings) {
      mesh.geometry.dispose();
      mesh.material.dispose();
    }
    this.renderer.dispose();
  }
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
