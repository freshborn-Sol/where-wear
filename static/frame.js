/* PC·노트북에서 열면 휴대폰 모양 틀 안에 화면을 보여 준다 (고객 QR · 직원 화면).
   - 진짜 휴대폰(가로 760px 미만) · 키오스크 · 주소에 ?noframe=1 이면 그대로 전체 화면
   - 틀 안에서는 같은 주소를 iframe으로 열고, 안에서 이동하면 바깥 주소도 따라 바뀐다 */
(function () {
  var inFrame;
  try { inFrame = window.self !== window.top; } catch (e) { inFrame = true; }
  if (inFrame) { document.documentElement.className += ' ww-inframe'; return; }
  var p = location.pathname, q = location.search;
  if (/^\/kiosk/.test(p) || /(^|[?&])noframe=1/.test(q) || window.innerWidth < 760) return;
  if (!/^\/(go|search|item|likes|me|info|credits|cats|map|staff|demo)?(\/|$)/.test(p)) return;
  // 이 문서의 나머지(원래 화면)는 읽지 않고 숨긴다 → 원래 화면의 스크립트가 바깥에서 두 번 돌지 않음
  document.write('<plaintext style="display:none">');
  var STAFF = /^\/(staff|demo)/.test(p);
  var CSS = [
    'html,body{margin:0;height:100%;background:#E6EAE7;font-family:"Noto Sans KR","Apple SD Gothic Neo",system-ui,sans-serif}',
    '.wwf{position:fixed;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;overflow:hidden;',
    ' background:radial-gradient(1200px 700px at 50% 30%,#F4F6F4 0%,#E3E8E4 60%,#D9DFDA 100%)}',
    '.wwf-stage{width:414px;height:868px;flex:none;transform-origin:center center}',
    '.wwf-phone{width:414px;height:868px;border-radius:64px;background:#17191A;padding:12px;box-sizing:border-box;',
    ' box-shadow:0 0 0 2px #3A3D3F inset,0 30px 70px rgba(20,30,25,.28),0 6px 16px rgba(20,30,25,.18)}',
    '.wwf-screen{position:relative;width:390px;height:844px;border-radius:52px;overflow:hidden;background:#fff}',
    '.wwf-sb{position:absolute;left:0;right:0;top:0;height:47px;display:flex;align-items:center;justify-content:space-between;',
    ' padding:4px 30px 0 40px;box-sizing:border-box;font-size:16px;font-weight:700;letter-spacing:-.01em;z-index:2;transition:background .2s,color .2s}',
    '.wwf-island{position:absolute;left:50%;top:11px;width:122px;height:34px;margin-left:-61px;border-radius:20px;background:#000}',
    '.wwf-ic{display:flex;align-items:center;gap:6px}',
    '.wwf-if{position:absolute;left:0;top:47px;width:390px;height:797px;border:0;display:block;background:#fff}',
    '.wwf-home{position:absolute;left:50%;bottom:8px;width:134px;height:5px;margin-left:-67px;border-radius:3px;background:#111;z-index:3;pointer-events:none}',
    '.wwf-cap{font-size:13px;color:#5C665F;display:flex;gap:6px;align-items:center;flex:none}',
    '.wwf-cap b{color:#2C302D}.wwf-cap a{color:#306A50;font-weight:700;text-decoration:none}',
    '.wwf-cap .sep{color:#B5BDB7}'
  ].join('\n');
  var ICONS = '<svg width="18" height="12" viewBox="0 0 18 12" fill="currentColor"><rect x="0" y="8" width="3" height="4" rx="1"/><rect x="5" y="5.5" width="3" height="6.5" rx="1"/><rect x="10" y="3" width="3" height="9" rx="1"/><rect x="15" y="0" width="3" height="12" rx="1"/></svg>' +
    '<svg width="16" height="12" viewBox="0 0 16 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M1.5 4.5a9.5 9.5 0 0 1 13 0M4 7.3a6 6 0 0 1 8 0"/><circle cx="8" cy="10" r="1.2" fill="currentColor" stroke="none"/></svg>' +
    '<svg width="27" height="13" viewBox="0 0 27 13" fill="none"><rect x=".5" y=".5" width="23" height="12" rx="3.5" stroke="currentColor" opacity=".45"/><rect x="2.5" y="2.5" width="19" height="8" rx="2" fill="currentColor"/><rect x="25" y="4.5" width="1.6" height="4" rx=".8" fill="currentColor" opacity=".45"/></svg>';
  function lum(rgb) {
    var m = (rgb || '').match(/\d+(\.\d+)?/g); if (!m) return 1;
    return (0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2]) / 255;
  }
  function topColor(d) {
    var meta = d.querySelector('meta[name="ww-top"]'); if (meta) return meta.content;
    var el = d.elementFromPoint(40, 6);
    while (el && el !== d.documentElement) {
      var c = d.defaultView.getComputedStyle(el).backgroundColor;
      if (c && c !== 'transparent' && !/rgba\(.*,\s*0\)$/.test(c)) return c;
      el = el.parentElement;
    }
    return '#ffffff';
  }
  function hexToRgb(h) { if (h[0] !== '#') return h; var n = parseInt(h.slice(1), 16); return 'rgb(' + (n >> 16 & 255) + ',' + (n >> 8 & 255) + ',' + (n & 255) + ')'; }
  function build() {
    var st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st);
    var w = document.createElement('div'); w.className = 'wwf';
    w.innerHTML = '<div class="wwf-stage"><div class="wwf-phone"><div class="wwf-screen">' +
      '<div class="wwf-sb"><span>9:41</span><span class="wwf-island"></span><span class="wwf-ic">' + ICONS + '</span></div>' +
      '<iframe class="wwf-if" title="where:wear" allow="camera; microphone; geolocation; clipboard-write; fullscreen; autoplay"></iframe>' +
      '<i class="wwf-home"></i></div></div></div>' +
      '<div class="wwf-cap"><b>where:wear</b><span class="sep">·</span><span id="wwfName">' + (STAFF ? '직원 화면' : '고객 QR 화면') +
      '</span><span class="sep">·</span><span>휴대폰에서는 전체 화면으로 보여요</span><span class="sep">·</span><a id="wwfOut" href="#">전체 화면으로 보기</a></div>';
    document.body.appendChild(w);
    var f = w.querySelector('iframe'), sb = w.querySelector('.wwf-sb'), stage = w.querySelector('.wwf-stage');
    var out = document.getElementById('wwfOut'), name = document.getElementById('wwfName');
    function noframe(u) { return u + (u.indexOf('?') < 0 ? '?' : '&') + 'noframe=1'; }
    out.href = noframe(location.href);
    f.src = location.href;
    f.addEventListener('load', function () {
      try {
        var cw = f.contentWindow, d = cw.document, u = cw.location.href;
        if (u !== location.href) history.replaceState(null, '', u);
        document.title = d.title || 'where:wear';
        out.href = noframe(u);
        name.textContent = /\/(staff|demo)/.test(cw.location.pathname) ? '직원 화면' : '고객 QR 화면';
        var c = hexToRgb(topColor(d));
        sb.style.background = c; sb.style.color = lum(c) < 0.55 ? '#fff' : '#111';
      } catch (e) {}
    });
    function fit() {
      var s = Math.min(1, (window.innerHeight - 70) / 868, (window.innerWidth - 40) / 414);
      stage.style.transform = 'scale(' + s + ')';
      stage.style.margin = (-(868 * (1 - s)) / 2) + 'px ' + (-(414 * (1 - s)) / 2) + 'px';
    }
    fit(); window.addEventListener('resize', fit);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build); else build();
})();
