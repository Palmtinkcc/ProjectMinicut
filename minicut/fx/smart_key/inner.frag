uniform int u_n; uniform vec2 u_in_sz;
void main() { float m = 1.0; int n2 = u_n * u_n;
  for (int j = -u_n; j <= u_n; j++) { int hw = int(floor(sqrt(float(n2 - j * j)) + 0.5));
    for (int i = -hw; i <= hw; i++) {
      float a = texture(u_in, v_uv + vec2(float(i), float(j)) / u_in_sz).r; m = min(m, a > 0.97 ? 1.0 : 0.0); } }
  o = vec4(m, m, m, 1.0); }
