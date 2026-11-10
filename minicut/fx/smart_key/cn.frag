uniform sampler2D u_col, u_inner;
void main() { float k = texture(u_inner, v_uv).r; o = vec4(texture(u_col, v_uv).rgb * k, 1.0); }
