precision highp float;

in vec2 vUv;
in vec2 vLocal;
flat in vec4 vState;

uniform sampler2D uAtlas;

out vec4 fragColor;

void main() {
  float text = texture(uAtlas, vUv).a;
  // Files in the blast radius are brighter (DESIGN.md "Ring").
  float ink = vState.y > 0.5 ? 1.0 : 0.72;
  vec3 rgb = mix(vec3(0.043), vec3(0.86), text * ink);
  // A thin --hot edge on changed files: the content card's leading side.
  if (vState.z > 0.5 && vState.w < 0.5 && vLocal.y < 0.08) {
    rgb = vec3(1.0);
  }
  // Faint separators so neighbouring cards read as blocks.
  float edge = max(step(vLocal.y, 0.03), step(0.97, vLocal.y));
  rgb = mix(rgb, vec3(0.16), edge * 0.6);
  fragColor = vec4(rgb, 0.94);
}
