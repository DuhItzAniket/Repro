precision highp float;

in vec4 vColor;
in float vAcross;
in float vHalfWidth;

uniform float uDpr;

out vec4 fragColor;

void main() {
  // Pixel coverage across the line, in device pixels: thin lines stay crisp at any DPR, and a
  // line narrower than a pixel fades instead of disappearing.
  float coverage = clamp((vHalfWidth - abs(vAcross)) * uDpr + 0.5, 0.0, 1.0);
  fragColor = vec4(vColor.rgb, vColor.a * coverage);
}
