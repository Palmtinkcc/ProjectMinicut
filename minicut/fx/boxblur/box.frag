uniform ivec2 u_dir; uniform int u_r; uniform vec2 u_in_sz;
void main() { ivec2 p = ivec2(gl_FragCoord.xy); ivec2 n = ivec2(u_in_sz); vec4 acc = vec4(0.0);
  for (int i = -u_r; i <= u_r; i++) acc += texelFetch(u_in, clamp(p + u_dir * i, ivec2(0), n - 1), 0);
  o = acc / float(2 * u_r + 1); }
