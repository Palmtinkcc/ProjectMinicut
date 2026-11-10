uniform vec2 u_in_sz;
int pmod(int a, int b) { return a - b * int(floor(float(a) / float(b))); }                                        // never negative (the % operator on a negative number differs between drivers)
int rfl(int i, int n) { int m = pmod(i, 2 * n); return m >= n ? 2 * n - 1 - m : m; }          // BORDER_REFLECT
int rfl101(int i, int n) { if (n < 2) return 0; int P = 2 * (n - 1); int m = pmod(i, P); return m >= n ? P - m : m; }   // BORDER_REFLECT_101
vec4 fetch(ivec2 i) { ivec2 n = ivec2(u_in_sz); return texelFetch(u_in, ivec2(rfl(i.x, n.x), rfl(i.y, n.y)), 0); }
vec4 bil(vec2 s) { vec2 f = floor(s); vec2 t = s - f; ivec2 i = ivec2(f);                                           // cv2.remap INTER_LINEAR, pixel index coordinates
  return mix(mix(fetch(i), fetch(i + ivec2(1, 0)), t.x), mix(fetch(i + ivec2(0, 1)), fetch(i + ivec2(1, 1)), t.x), t.y); }
