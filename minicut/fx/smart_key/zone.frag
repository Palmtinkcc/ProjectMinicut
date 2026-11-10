uniform sampler2D u_inner;
void main() { float a = texture(u_in, v_uv).r; float solid = a > 0.97 ? 1.0 : 0.0; float ring = solid - texture(u_inner, v_uv).r;
  float partial = (a > 0.004 && a <= 0.97) ? 1.0 : 0.0; float z = max(ring, partial); o = vec4(z, z, z, 1.0); }
