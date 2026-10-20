/* A slow, moving brand gradient drawn with WebGL (the look of shadergradient, without React or
   three.js: one small shader). Used behind the welcome screen of the tour and the About header.

   SabaGradient.mount(canvas) -> { stop() }
   - "Reduce motion" on the phone/computer: draws one still frame, no animation.
   - Tab hidden: pauses. No WebGL: leaves the canvas empty so the CSS gradient behind it shows. */
window.SabaGradient = (function () {
  const VERT = "attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}";
  // soft value noise, warped twice, mixed into navy -> teal -> brass
  const FRAG = [
    "precision mediump float;",
    "uniform vec2 r;uniform float t;",
    "float h(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}",
    "float n(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);",
    " return mix(mix(h(i),h(i+vec2(1,0)),f.x),mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x),f.y);}",
    "float fbm(vec2 p){float v=0.,a=.5;for(int k=0;k<4;k++){v+=a*n(p);p*=2.02;a*=.5;}return v;}",
    "void main(){",
    " vec2 uv=gl_FragCoord.xy/r.xy;vec2 p=uv*vec2(r.x/r.y,1.)*1.6;",
    " float s=t*.035;",
    " vec2 q=vec2(fbm(p+s),fbm(p+vec2(5.2,1.3)-s));",
    " float f=fbm(p+2.2*q+vec2(1.7,9.2)+s*.6);",
    " vec3 navy=vec3(.039,.086,.157),deep=vec3(.06,.16,.28),teal=vec3(.05,.34,.40),brass=vec3(.85,.64,.25);",
    " vec3 c=mix(navy,deep,smoothstep(.2,.6,f));",
    " c=mix(c,teal,smoothstep(.45,.85,q.x)*.55);",
    " c=mix(c,brass,smoothstep(.62,.95,f*q.y*1.6)*.55);",
    " c*=.85+.25*uv.y;",                       // a little lighter at the top
    " c+=(h(gl_FragCoord.xy+t)-.5)*.018;",     // fine grain, avoids colour banding
    " gl_FragColor=vec4(c,1.);}",
  ].join("\n");

  function mount(canvas) {
    let gl = null;
    try { gl = canvas.getContext("webgl", { antialias: false, premultipliedAlpha: false }); } catch (e) {}
    if (!gl) return { stop() {} };

    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
    const prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return { stop() {} };
    gl.useProgram(prog);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const uR = gl.getUniformLocation(prog, "r"), uT = gl.getUniformLocation(prog, "t");

    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0, alive = true;
    const t0 = performance.now() - 40000 * Math.random(); // a different start each time

    function size() {
      // half resolution: it is a soft blur anyway, and phones stay cool
      const scale = Math.min(window.devicePixelRatio || 1, 2) * 0.5;
      const w = Math.max(1, Math.round(canvas.clientWidth * scale)), h = Math.max(1, Math.round(canvas.clientHeight * scale));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, w, h);
      gl.uniform2f(uR, w, h);
    }
    function frame(now) {
      if (!alive) return;
      size();
      gl.uniform1f(uT, (now - t0) / 1000);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      if (!still && !document.hidden) raf = requestAnimationFrame(frame);
    }
    const wake = () => { if (alive && !still && !document.hidden) { cancelAnimationFrame(raf); raf = requestAnimationFrame(frame); } };
    document.addEventListener("visibilitychange", wake);
    addEventListener("resize", wake);
    raf = requestAnimationFrame(frame);
    if (still) addEventListener("resize", () => alive && requestAnimationFrame(frame));

    return {
      stop() {
        alive = false;
        cancelAnimationFrame(raf);
        document.removeEventListener("visibilitychange", wake);
        removeEventListener("resize", wake);
      },
    };
  }
  return { mount };
})();
