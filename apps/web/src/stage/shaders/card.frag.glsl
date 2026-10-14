precision highp float;

in vec2 vUv;
in vec2 vLocal;
flat in vec4 vState;

uniform sampler2D uAtlas;

out vec4 fragColor;

// Band layout in units across it (see atlas.ts): bezel, content, outer comb.
const float UNITS = 160.0;
const vec3 FLAG = vec3(0.706, 0.561, 0.612); // --flag

void main() {
  float u = vLocal.x * UNITS;
  // The band's own shading: a lit bezel along the inner rim, a dark groove, the dark card
  // ground, and a slightly lighter outer zone under the comb (B14, from the reference).
  float bezel = (1.0 - smoothstep(0.0, 11.0, u)) * 0.2;
  float groove = 1.0 - smoothstep(10.5, 12.5, u) * (1.0 - smoothstep(12.5, 14.0, u));
  vec3 rgb = vec3((0.04 + bezel) * groove + 0.02 * step(151.0, u));

  if (vState.w < 1.5) {
    vec4 ink = texture(uAtlas, vUv);
    // Plain ink is white and changed rows are red in the atlas: green over red tells them apart
    // with or without premultiplied alpha.
    float flag = ink.a > 0.004 ? 1.0 - clamp(ink.g / max(ink.r, 1e-4), 0.0, 1.0) : 0.0;
    // Files in the blast radius are brighter (DESIGN.md "Ring").
    float bright = vState.y > 0.5 ? 1.0 : 0.8;
    vec3 colour = mix(vec3(0.88), FLAG, flag) * bright;
    rgb = mix(rgb, colour, clamp(ink.a, 0.0, 1.0));
    // A one-pixel dark seam between neighbouring cards, outside the bezel.
    float px = fwidth(vLocal.y);
    float seam = 1.0 - smoothstep(0.0, 1.5 * px, min(vLocal.y, 1.0 - vLocal.y));
    rgb = mix(rgb, vec3(0.0), seam * step(13.0, u) * 0.85);
    // A thin --hot edge on changed files, along the card's leading side.
    if (vState.z > 0.5 && u > 13.0 && u < 151.0 && vLocal.y < 1.2 * px) rgb = vec3(0.62);
  }
  fragColor = vec4(rgb, 1.0);
}
