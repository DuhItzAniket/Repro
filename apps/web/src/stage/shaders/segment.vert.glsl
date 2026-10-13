precision highp float;

// Unit quad corner: x = 0 at the segment start, 1 at its end; y = -1 or +1 across it.
in vec2 corner;
// Per instance (see SEGMENT_ATTRIBUTES).
in vec2 a;
in vec2 b;
in vec4 color;
in vec2 shape;

uniform vec2 uViewport; // stage size in CSS px
uniform float uDpr;

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

  vAcross = across;
  vHalfWidth = halfWidth;
  vColor = vec4(color.rgb, color.a * mix(shape.y, 1.0, corner.x));

  vec2 clip = p / uViewport * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
}
