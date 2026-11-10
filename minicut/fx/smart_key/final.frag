uniform sampler2D u_col, u_A, u_z, u_cn, u_cd; uniform float u_amt; uniform vec3 u_ecol; uniform int u_mode, u_view;
void main() {
  vec3 col = texture(u_col, v_uv).rgb; float A = texture(u_A, v_uv).r;
  float z = (u_mode > 0 || u_view == 2) ? clamp(texture(u_z, v_uv).r * 1.6, 0.0, 1.0) : 0.0;
  if (u_view == 1) { o = vec4(vec3(A), 1.0); return; }
  if (u_view == 2) { o = vec4(vec3(z), 1.0); return; }
  if (u_mode == 2) col = mix(col, u_ecol, z * u_amt);
  else if (u_mode == 1) { float den = texture(u_cd, v_uv).r; vec3 ec = den > 1e-3 ? texture(u_cn, v_uv).rgb / max(den, 1e-3) : col; col = mix(col, ec, z * u_amt); }
  o = vec4(clamp(col, 0.0, 1.0), A); }
