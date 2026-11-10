uniform vec2 u_kc; uniform float u_t0, u_wd;
void main() { vec4 c = texture(u_in, v_uv); float R = floor(c.b * 255.0 + 0.5), G = floor(c.g * 255.0 + 0.5), B = floor(c.r * 255.0 + 0.5);
  float Y = floor(0.299 * R + 0.587 * G + 0.114 * B + 0.5);                       // the 8-bit YCrCb of the CPU version (Y is rounded first)
  float cr = clamp(floor((R - Y) * 0.713 + 128.5), 0.0, 255.0), cb = clamp(floor((B - Y) * 0.564 + 128.5), 0.0, 255.0);
  float d = length(vec2(cr - u_kc.x, cb - u_kc.y)); float t = clamp((d - u_t0) / u_wd, 0.0, 1.0);
  float a = t * t * (3.0 - 2.0 * t) * c.a; o = vec4(a, a, a, 1.0); }
