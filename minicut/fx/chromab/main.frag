//#use sampling
uniform float u_k; uniform vec2 u_o;
void main() { vec2 xy = floor(gl_FragCoord.xy); vec2 cen = u_in_sz * 0.5; vec4 c = texelFetch(u_in, ivec2(xy), 0);
  float rr = bil(cen + (xy - cen) * (1.0 - u_k) + u_o).b;            // R (index 2) is the b component
  float bb = bil(cen + (xy - cen) * (1.0 + u_k) - u_o).r;            // B (index 0)
  o = vec4(bb, c.g, rr, c.a); }
