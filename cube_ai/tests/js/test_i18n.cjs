const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag, children = []) { this.nodeType = 1; this.tagName = tag; this.childNodes = children; this.attrs = {}; children.forEach(c => c.parentElement = this); }
  hasAttribute(n) { return Object.hasOwn(this.attrs, n); }
  setAttribute(n, v) { this.attrs[n] = v; }
  getAttribute(n) { return this.attrs[n]; }
  addEventListener(n, f) { this[n] = f; }
}
const text = value => ({nodeType: 3, nodeValue: value});
const optionText = text('选项');
const option = new Element('OPTION', [optionText]);
const report = new Element('A');
report.setAttribute('href', '/exports/abc/report.md');
const content = text('你好');
const dynamic = text('找到 7 张牌：颜色身份 WU');
const metric = text('当前最低要求：互动 45 张 · 扫场 9 张 · 终结 22 张。');
const root = new Element('HTML', [new Element('DIV', [content]), new Element('DIV', [dynamic]), new Element('DIV', [metric]), option, report]);
const selector = new Element('SELECT');
const preview = new Element('DIV');
let observer;
const context = {document: {documentElement: root, getElementById: id => id === 'ui-language' ? selector : preview},
  window: {}, localStorage: {getItem() { return 'en'; }, setItem() {}},
  MutationObserver: class { constructor(fn) { observer = fn; } observe() {} },
  fetch: async () => ({ok: true, json: async () => ({'你好': 'Hello', '选项': 'Option', '再见': 'Goodbye', '颜色身份': 'Color identity'})})};
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), context);
setImmediate(() => {
  assert.equal(content.nodeValue, 'Hello');
  assert.equal(optionText.nodeValue, 'Option');
  assert.equal(option.getAttribute('value'), '选项');
  assert.equal(report.getAttribute('href'), '/exports/abc/report.md?lang=en');
  assert.equal(dynamic.nodeValue, '找到 7 张牌：Color identity WU');
  assert.equal(metric.nodeValue, 'Configured minimums: 45 interaction · 9 board wipes · 22 finishers.');
  assert.equal(preview.hidden, false);
  content.nodeValue = '再见';
  observer([{type: 'characterData', target: content}]);
  assert.equal(content.nodeValue, 'Goodbye');
  context.window.cubeI18n.setLanguage('zh-CN');
  assert.equal(content.nodeValue, '再见');
  assert.equal(dynamic.nodeValue, '找到 7 张牌：颜色身份 WU');
  assert.equal(metric.nodeValue, '当前最低要求：互动 45 张 · 扫场 9 张 · 终结 22 张。');
  assert.equal(optionText.nodeValue, '选项');
  assert.equal(option.getAttribute('value'), '选项');
  assert.equal(report.getAttribute('href'), '/exports/abc/report.md');
  assert.equal(preview.hidden, true);
  console.log('i18n checks passed');
});
