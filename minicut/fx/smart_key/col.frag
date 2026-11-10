uniform vec3 u_dom, u_oth; uniform float u_cnt, u_amt;
void main() { vec3 x = texture(u_in, v_uv).rgb;
  if (u_amt > 0.0 && u_cnt > 0.0) { float lim = dot(x, u_oth) / u_cnt; x = mix(x, min(x, vec3(lim)), u_dom * u_amt); }
  o = vec4(x, 1.0); }
