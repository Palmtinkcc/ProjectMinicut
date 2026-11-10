uniform mat3 u_kern; uniform float u_mix; uniform int u_color; uniform vec2 u_in_sz;
int r101(int i, int n) { if (n < 2) return 0; int P = 2 * (n - 1); int m = i - P * int(floor(float(i) / float(P))); return m >= n ? P - m : m; }
float L(ivec2 p) { ivec2 n = ivec2(u_in_sz); return lum(texelFetch(u_in, ivec2(r101(p.x, n.x), r101(p.y, n.y)), 0).rgb); }
void main() { ivec2 p = ivec2(gl_FragCoord.xy); vec4 c = texture(u_in, v_uv); float g = 0.0;
  for (int j = 0; j < 3; j++) for (int i = 0; i < 3; i++) g += u_kern[i][j] * L(p + ivec2(i - 1, j - 1));     // u_kern[col i][row j]
  float rel = clamp(0.5 + g * 0.5, 0.0, 1.0);
  vec3 e = u_color == 0 ? vec3(rel) : c.rgb * rel * 2.0; o = vec4(clamp(c.rgb * (1.0 - u_mix) + e * u_mix, 0.0, 1.0), c.a); }
