//#use sampling
uniform ivec2 u_f;
void main() { ivec2 p = ivec2(gl_FragCoord.xy); ivec2 n = ivec2(u_in_sz); if (u_f.x == 1) p.x = n.x - 1 - p.x; if (u_f.y == 1) p.y = n.y - 1 - p.y; o = texelFetch(u_in, p, 0); }
