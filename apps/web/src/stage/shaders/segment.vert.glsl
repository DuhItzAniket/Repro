precision highp float;

// Unit quad corner: x = 0 at the segment start, 1 at its end; y = -1 or +1 across it.
in vec2 corner;
// Per instance (see SEGMENT_ATTRIBUTES).
in vec2 a;
in vec2 b;
in vec4 color;
in vec2 shape;
in float appear;
in float flare; // this segment's share of the layer's flare (the flash governor's decision)

uniform vec2 uViewport; // stage size in CSS px
uniform float uDpr;
uniform float uTime; // presentation time, ms
uniform float uFlare; // recency: extra alpha multiple right after appearing
uniform float uFlareMs; // recency decay time constant, presentation ms (wall-clock × speed)
uniform float uFadeMs; // > 0: fade linearly to nothing over this much run time after appearing
uniform float uGrowMs; // > 0: grow from start to end over this many presentation ms after appearing
uniform vec2 uCenter; // rotation centre, stage px (the ring's centre)
uniform vec2 uSpin; // cos and sin of the layer's rotation (1, 0 for layers that do not turn)

out vec4 vColor;
out float vAcross; // signed distance from the centre line, CSS px
out float vHalfWidth;

vec2 spin(vec2 p) {
  vec2 q = p - uCenter;
  return uCenter + vec2(q.x * uSpin.x - q.y * uSpin.y, q.x * uSpin.y + q.y * uSpin.x);
}

void main() {
  float dt = uTime - appear;
  vec2 pa = spin(a);
  vec2 pb = spin(b);
  // Growth (mirrors growFactor in segments.ts): the end runs out from the start.
  pb = pa + (pb - pa) * (uGrowMs > 0.0 ? clamp(dt / uGrowMs, 0.0, 1.0) : 1.0);
  vec2 d = pb - pa;
  float len = length(d);
  vec2 dir = len > 1e-4 ? d / len : vec2(1.0, 0.0);
  vec2 normal = vec2(-dir.y, dir.x);
  // One device pixel of margin across the segment for anti-aliasing. None along it: arcs are
  // chains of segments, and overlapping ends would add up into bright dots at every joint (B14).
  float margin = 1.0 / uDpr;
  float halfWidth = 0.5 * shape.x;
  float along = corner.x * len;
  float across = corner.y * (halfWidth + margin);
  vec2 p = pa + dir * along + normal * across;

  // Recency (mirrors recencyFactor in segments.ts): hidden before `appear`, then a flare that
  // decays back to the base alpha.
  float fade = uFadeMs > 0.0 ? max(0.0, 1.0 - dt / uFadeMs) : 1.0;
  float recency = dt < 0.0 ? 0.0 : (1.0 + uFlare * flare * exp(-dt / uFlareMs)) * fade;

  vAcross = across;
  vHalfWidth = halfWidth;
  vColor = vec4(color.rgb, min(1.0, color.a * recency) * mix(shape.y, 1.0, corner.x));

  // Segments that are not visible yet collapse to a point and cost no fill.
  vec2 clip = p / uViewport * 2.0 - 1.0;
  gl_Position = recency > 0.0 ? vec4(clip.x, -clip.y, 0.0, 1.0) : vec4(2.0, 2.0, 2.0, 1.0);
}
