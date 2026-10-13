precision highp float;

// Unit quad corner: x = 0 at the inner radius, 1 at the outer; y = -1 or +1 across the card.
in vec2 corner;
// Per instance (see CARD_ATTRIBUTES).
in vec4 span; // start angle, end angle (rad, before rotation), inner and outer offset from the ring radius (px)
in vec4 uv; // u0, v0, u1, v1 in the atlas
in vec4 times; // appears, joins the blast radius, is changed (presentation ms); kind (0 content, 1 metadata)

uniform vec2 uViewport; // stage size in CSS px
uniform vec2 uCenter; // ring centre, stage px
uniform float uRadius; // ring radius, px
uniform float uRotation; // closed-form ring rotation at uTime (rad)
uniform float uTime; // presentation time, ms

out vec2 vUv;
out vec2 vLocal; // 0–1 radially (x) and across the card (y)
flat out vec4 vState; // visible, in the blast radius, changed, kind

void main() {
  float radial = corner.x;
  float across = corner.y * 0.5 + 0.5;
  float theta = mix(span.x, span.y, across) + uRotation;
  float r = uRadius + mix(span.z, span.w, radial);
  vec2 p = uCenter + vec2(cos(theta), sin(theta)) * r;

  vUv = vec2(mix(uv.x, uv.z, radial), mix(uv.y, uv.w, across));
  vLocal = vec2(radial, across);
  float visible = uTime >= times.x ? 1.0 : 0.0;
  vState = vec4(visible, uTime >= times.y ? 1.0 : 0.0, uTime >= times.z ? 1.0 : 0.0, times.w);

  // Cards that have not appeared yet collapse to a point and cost no fill.
  vec2 clip = p / uViewport * 2.0 - 1.0;
  gl_Position = visible > 0.0 ? vec4(clip.x, -clip.y, 0.0, 1.0) : vec4(2.0, 2.0, 2.0, 1.0);
}
