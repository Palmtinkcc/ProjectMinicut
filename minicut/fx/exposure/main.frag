uniform float u_ev, u_off, u_ig;
void main() { vec4 c = texture(u_in, v_uv); vec3 f = clamp(c.rgb * u_ev + u_off, 0.0, 8.0); o = vec4(clamp(pow(f, vec3(u_ig)), 0.0, 1.0), c.a); }
