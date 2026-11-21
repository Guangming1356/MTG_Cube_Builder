/* Offline interface translations. Generated content can remain in its original language. */
(() => {
  const selector = document.getElementById('ui-language');
  const preview = document.getElementById('language-preview');
  if (!selector) return;
  const originals = new WeakMap();
  const attributeOriginals = new WeakMap();
  const attributes = ['title', 'placeholder', 'aria-label'];
  let dictionary = {};
  let language = 'zh-CN';

  function translated(value) {
    const match = /^(\s*)(.*?)(\s*)$/s.exec(value);
    return match && Object.prototype.hasOwnProperty.call(dictionary, match[2])
      ? match[1] + dictionary[match[2]] + match[3] : value;
  }

  function textNode(node) {
    const parent = node.parentElement;
    if (!parent || /^(SCRIPT|STYLE|TEXTAREA|PRE|CODE)$/.test(parent.tagName)) return;
    const previous = originals.get(node);
    let original = previous && (node.nodeValue === previous.rendered || node.nodeValue === previous.original)
      ? previous.original : node.nodeValue;
    const rendered = language === 'en' ? translated(original) : original;
    if (rendered !== original && parent.tagName === 'OPTION' && !parent.hasAttribute('value')) {
      parent.setAttribute('value', original.trim());
    }
    originals.set(node, {original, rendered});
    if (node.nodeValue !== rendered) node.nodeValue = rendered;
  }

  function element(node) {
    let state = attributeOriginals.get(node) || {};
    for (const name of attributes) {
      if (!node.hasAttribute(name)) continue;
      const value = node.getAttribute(name);
      const previous = state[name];
      const original = previous && (value === previous.rendered || value === previous.original)
        ? previous.original : value;
      const rendered = language === 'en' ? translated(original) : original;
      state[name] = {original, rendered};
      if (value !== rendered) node.setAttribute(name, rendered);
    }
    attributeOriginals.set(node, state);
  }

  function visit(node) {
    if (node.nodeType === 3) return textNode(node);
    if (node.nodeType !== 1) return;
    element(node);
    for (const child of node.childNodes) visit(child);
  }

  function setLanguage(value) {
    language = value === 'en' ? 'en' : 'zh-CN';
    selector.value = language;
    document.documentElement.lang = language;
    if (preview) preview.hidden = language !== 'en';
    try { localStorage.setItem('cube-ui-language', language); } catch (_) { /* optional */ }
    visit(document.documentElement);
  }

  selector.addEventListener('change', () => setLanguage(selector.value));
  new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData') visit(record.target);
      else if (record.type === 'attributes') element(record.target);
      else for (const node of record.addedNodes) visit(node);
    }
  }).observe(document.documentElement, {subtree: true, childList: true, characterData: true,
    attributes: true, attributeFilter: attributes});
  let initial = 'zh-CN';
  try { initial = localStorage.getItem('cube-ui-language') || initial; } catch (_) { /* optional */ }
  fetch('/i18n_en.json').then(response => {
    if (!response.ok) throw new Error('Translation dictionary unavailable');
    return response.json();
  }).then(data => { dictionary = data; setLanguage(initial); })
    .catch(() => { selector.disabled = true; setLanguage('zh-CN'); });
  window.cubeI18n = {setLanguage};
})();
