(function () {
  'use strict';

  const React = { createRef: () => ({ current: null }) };

  let _uid = 0;
  const _h = {};

  function uid() { return 'dc' + ++_uid; }

  function extractExpr(s) {
    const m = s && s.match(/^\s*\{\{\s*([\s\S]*?)\s*\}\}\s*$/);
    return m ? m[1].trim() : null;
  }

  function hasExpr(s) { return !!(s && s.includes('{{') && s.includes('}}')); }

  function evalPath(expr, vals, scope) {
    if (!expr) return undefined;
    const parts = expr.trim().split('.');
    if (parts[0] && scope && Object.prototype.hasOwnProperty.call(scope, parts[0])) {
      let v = scope[parts[0]];
      for (let i = 1; i < parts.length; i++) v = v == null ? undefined : v[parts[i]];
      return v;
    }
    let v = vals;
    for (const p of parts) v = v == null ? undefined : v[p];
    return v;
  }

  function interpolate(s, vals, scope) {
    return s.replace(/\{\{\s*([\s\S]*?)\s*\}\}/g, (_, e) => {
      const v = evalPath(e.trim(), vals, scope);
      return v == null || typeof v === 'function' ? '' : v;
    });
  }

  window.__dcH = {};

  const EV = new Set(['onclick', 'oninput', 'onchange', 'onscroll', 'onkeydown', 'onkeyup', 'onfocus', 'onblur']);

  function processNode(node, vals, scope, refs) {
    if (node.nodeType === 3) {
      if (hasExpr(node.textContent)) node.textContent = interpolate(node.textContent, vals, scope);
      return;
    }
    if (node.nodeType !== 1) return;

    const tag = node.tagName.toLowerCase();

    if (tag === 'sc-for') {
      const listExpr = extractExpr(node.getAttribute('list') || '');
      const as = node.getAttribute('as') || '_item';
      const list = listExpr ? (evalPath(listExpr, vals, scope) || []) : [];
      const frag = document.createDocumentFragment();
      for (const item of list) {
        const ns = Object.assign({}, scope, { [as]: item });
        Array.from(node.childNodes).forEach(c => {
          const cl = c.cloneNode(true);
          processNode(cl, vals, ns, refs);
          frag.appendChild(cl);
        });
      }
      if (node.parentNode) {
        node.parentNode.replaceChild(frag, node);
      } else {
        node.innerHTML = '';
        Array.from(frag.childNodes).forEach(c => node.appendChild(c));
      }
      return;
    }

    if (tag === 'sc-if') {
      const expr = extractExpr(node.getAttribute('value') || '');
      const frag = document.createDocumentFragment();
      if (expr && evalPath(expr, vals, scope)) {
        Array.from(node.childNodes).forEach(c => {
          const cl = c.cloneNode(true);
          processNode(cl, vals, scope, refs);
          frag.appendChild(cl);
        });
      }
      if (node.parentNode) {
        if (expr && evalPath(expr, vals, scope)) {
          node.parentNode.replaceChild(frag, node);
        } else {
          node.parentNode.removeChild(node);
        }
      } else {
        node.innerHTML = '';
        if (expr && evalPath(expr, vals, scope)) {
          Array.from(frag.childNodes).forEach(c => node.appendChild(c));
        }
      }
      return;
    }

    for (const attr of Array.from(node.attributes)) {
      const name = attr.name.toLowerCase();
      const raw = attr.value;
      if (!hasExpr(raw)) continue;

      if (name === 'ref') {
        const ref = evalPath(extractExpr(raw), vals, scope);
        if (ref) { const id = uid(); refs[id] = ref; node.setAttribute('data-ref', id); }
        node.removeAttribute('ref');
      } else if (EV.has(name)) {
        const fn = evalPath(extractExpr(raw), vals, scope);
        if (typeof fn === 'function') {
          const id = uid();
          window.__dcH[id] = fn;
          // Replace {{ fn }} with a direct global call — avoids removeAttribute timing issues
          attr.value = 'window.__dcH["' + id + '"](event)';
        } else {
          attr.value = '';
        }
      } else if (name === 'checked') {
        const val = evalPath(extractExpr(raw), vals, scope);
        if (val) node.setAttribute('checked', ''); else node.removeAttribute('checked');
      } else {
        attr.value = interpolate(raw, vals, scope);
      }
    }

    Array.from(node.childNodes).forEach(c => processNode(c, vals, scope, refs));
  }

  class DCLogic {
    constructor() { this._mounted = false; }

    setState(u) {
      const prev = Object.assign({}, this.state);
      this.state = Object.assign({}, this.state, typeof u === 'function' ? u(this.state) : u);
      if (this._mounted) {
        this._render();
        this.componentDidUpdate && this.componentDidUpdate({}, prev);
      }
    }

    _render() {
      window.__dcH = {};
      const vals = this.renderVals();
      const refs = {};
      const clone = this._tmpl.cloneNode(true);
      Array.from(clone.childNodes).forEach(c => processNode(c, vals, {}, refs));

      this._root.innerHTML = '';
      while (clone.firstChild) this._root.appendChild(clone.firstChild);

      Object.entries(refs).forEach(([id, ref]) => {
        const el = this._root.querySelector('[data-ref="' + id + '"]');
        if (el) { ref.current = el; el.removeAttribute('data-ref'); }
      });

      this._root.querySelectorAll('input, textarea').forEach(el => {
        if (el.hasAttribute('value')) el.value = el.getAttribute('value');
        if (el.type === 'checkbox' || el.type === 'radio')
          el.checked = el.hasAttribute('checked');
      });
    }

    _mount(root, html) {
      this._root = root;
      this._tmpl = document.createElement('div');
      this._tmpl.innerHTML = html;
      this._render();
      this._mounted = true;
      this.componentDidMount && this.componentDidMount();
    }
  }

  window.DCLogic = DCLogic;
  window.React = React;

  function boot() {
    const xdc = document.querySelector('x-dc');
    if (!xdc) return;

    const helmet = xdc.querySelector('helmet');
    if (helmet) {
      Array.from(helmet.childNodes).forEach(n => document.head.appendChild(n));
      helmet.remove();
    }

    const scriptEl = xdc.querySelector('script[data-dc-script]');
    const src = scriptEl ? scriptEl.textContent : '';
    if (scriptEl) scriptEl.remove();

    const html = xdc.innerHTML;
    xdc.innerHTML = '';

    const Comp = new Function('DCLogic', 'React', src + '\nreturn Component;')(DCLogic, React);
    const inst = new Comp();
    inst._mount(xdc, html);
    xdc.style.display = '';
  }

  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', boot);
  else
    boot();
})();
