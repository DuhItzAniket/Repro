precision highp float;

// Unit quad corner: x = 0 at the segment start, 1 at its end; y = -1 or +1 across it.
in vec2 corner;
// Per instance (see SEGMENT_ATTRIBUTES).
in vec2 a;
in vec2 b;
in vec4 color;
in vec2 shape;
in float appear;

uniform vec2 uViewport; // stage size in CSS px
uniform float uDpr;
uniform float uTime; // presentation time, ms
uniform float uFlare; // recency: extra alpha multiple right after appearing
uniform float uFlareMs; // recency decay time constant, ms

out vec4 vColor;
out float vAcross; // signed distance from the centre line, CSS px
out float vHalfWidth;

void main() {
  vec2 d = b - a;
  float len = length(d);
  vec2 dir = len > 1e-4 ? d / len : vec2(1.0, 0.0);
  vec2 normal = vec2(-dir.y, dir.x);
  // One device pixel of margin around the segment for anti-aliasing.
  float margin = 1.0 / uDpr;
  float halfWidth = 0.5 * shape.x;
  float along = corner.x * len + (corner.x * 2.0 - 1.0) * margin;
  float across = corner.y * (halfWidth + margin);
  vec2 p = a + dir * along + normal * across;

  // Recency (mirrors recencyFactor in segments.ts): hidden before `appear`, then a flare that
  // decays back to the base alpha.
  float dt = uTime - appear;
  float recency = dt < 0.0 ? 0.0 : 1.0 + uFlare * exp(-dt / uFlareMs);

  vAcross = across;
  vHalfWidth = halfWidth;
  vColor = vec4(color.rgb, min(1.0, color.a * recency) * mix(shape.y, 1.0, corner.x));

  // Segments that are not visible yet collapse to a point and cost no fill.
  vec2 clip = p / uViewport * 2.0 - 1.0;
  gl_Position = recency > 0.0 ? vec4(clip.x, -clip.y, 0.0, 1.0) : vec4(2.0, 2.0, 2.0, 1.0);
}
