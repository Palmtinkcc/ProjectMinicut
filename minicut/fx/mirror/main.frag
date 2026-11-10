//#use sampling
uniform int u_mode; uniform vec2 u_c;
void main() { vec2 xy = floor(gl_FragCoord.xy); vec2 s = xy;
  if (u_mode == 0 || u_mode == 4) s.x = xy.x > u_c.x ? 2.0 * u_c.x - xy.x : xy.x;
  if (u_mode == 1) s.x = xy.x < u_c.x ? 2.0 * u_c.x - xy.x : xy.x;
  if (u_mode == 2 || u_mode == 4) s.y = xy.y > u_c.y ? 2.0 * u_c.y - xy.y : xy.y;
  if (u_mode == 3) s.y = xy.y < u_c.y ? 2.0 * u_c.y - xy.y : xy.y;
  o = bil(s); }
