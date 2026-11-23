/* Offline interface translations. Generated content can remain in its original language. */
(() => {
  const selector = document.getElementById('ui-language');
  const preview = document.getElementById('language-preview');
  if (!selector) return;
  const originals = new WeakMap();
  const attributeOriginals = new WeakMap();
  const attributes = ['title', 'placeholder', 'aria-label', 'label', 'alt'];
  let dictionary = {};
  let fragments = {regex: /$^/g, lookup: {}};
  let language = 'en';
  const chinese = {
    'YOUR FORMAT, YOUR CUBE':'你的玩法，你的 Cube',
    'FORGE RULES ENGINE / AI SELF PLAY':'Forge 规则引擎 / AI 自我对局',
    'GROUNDED IN YOUR CARD POOL':'基于你的牌池',
    'LEARN FROM YOUR TABLE':'从牌桌反馈中学习',
    'DRAFT → PLAY → REVISE → VALIDATE':'轮抓 → 对局 → 改进 → 验证',
    'Continue with ChatGPT':'使用 ChatGPT 继续'
  };
  const dynamicRules = [
    [/^当前最低要求：互动\s*(\S+)\s*张\s*·\s*扫场\s*(\S+)\s*张\s*·\s*终结\s*(\S+)\s*张。$/, (_,a,b,c) => `Configured minimums: ${a} interaction · ${b} board wipes · ${c} finishers.`],
    [/^指挥官槽位\s*\/\s*合格传奇\s*(\S+)$/, (_,n) => `Commander slots / eligible commanders: ${n}`],
    [/^(\d+)\s*桌\s*·\s*可组牌率\s*([\d.]+)%$/, (_,pods,rate) => `${pods} draft pods · ${rate}% buildable decks`],
    [/^Bracket\s*(\d+)\s*构筑限制检查：(\d+)\s*副牌\s*·\s*(\d+)\s*副违规\s*·\s*每副牌最多观察到\s*(\d+)\s*张 Game Changers。$/, (_,bracket,decks,violations,max) => `Bracket ${bracket} construction checks: ${decks} decks · ${violations} violations · at most ${max} Game Changers observed in a deck.`],
    [/^实际组牌中\s*(\d+)\s*\/\s*(\d+)\s*副的牺牲或返场组件需要复核。$/, (_,incomplete,total) => `${incomplete}/${total} built decks have sacrifice or reanimation components that need review.`],
    [/^Vintage 抓牌参考 CubeCobra 全站选牌评分：(\d+)\s*\/\s*(\d+)\s*张有数据；其余牌沿用本项目评分。来源快照：(\d{4}-\d{2}-\d{2})。这不是实战胜率。$/, (_,covered,total,date) => `Vintage drafting uses CubeCobra's site-wide pick ratings for ${covered}/${total} cards; other cards use the project score. Source snapshot: ${date}. These ratings are not game win rates.`],
    [/^）：(\d+)\s*副牌的平均可识别去除评价\s*([\d.]+)；识别\s*(\d+)\s*\/\s*(\d+)\s*张互动。(.+)$/, (_,decks,score,classified,total,note) => `): mean recognized removal score ${score} across ${decks} decks; ${classified}/${total} interaction cards classified. ${translated(note)}`],
    [/^每副牌\s*(\d+)\s*手\s*·\s*每手观察\s*(\d+)\s*张牌。准备度抽样不影响后续轮抓。$/, (_,hands,cards) => `${hands} hands per deck · ${cards} cards observed per hand. Readiness sampling does not affect subsequent drafts.`],
    [/^每回合抽牌、最多下一张地，在已见地牌中选择来源；每张产法术力地只计一点，雪境来源单独检查。每个 X 按 1；非瑞克西亚费用按起始 (\d+) 生命、至少保留 1 点生命分别测试一张牌，.+费用可支付不代表一定能行动。$/, (_,life) => `Draw one card per turn and play at most one land, choosing sources from lands seen. Each mana-producing land provides one mana; snow sources are checked separately. Each X is one. Costs are tested independently with ${life} starting life while retaining at least one life; earlier life payments and damage are not accumulated. No mana cost is not the same as {0}. Recognized mandatory additional mana and resource-or-mana costs use their mana-only branch; waterbend does not use tapping assistance. Ramp, tapped lands, conditional mana, cost changes, other additional or alternative costs, mulligans, legal targets and card effects are not simulated. Being able to pay a cost does not guarantee an action.`],
    [/^·\s*组牌：(.+?)\s*·\s*抓牌池张数\s*(.+?)\s*·\s*每包弃\s*(\d+)\s*张$/, (_,policy,pools,discard) => `· Deck policy: ${translated(policy)} · Drafted pool sizes: ${pools} · ${discard} cards discarded per pack`],
    [/^因牌组未获引擎支持跳过\s*(\d+)\s*个配对，原始牌组未更改。$/, (_,n) => `${n} pairings involving unsupported decks were skipped; the original decks were not changed.`],
    [/^同时最多\s*(\d+)\s*局\s*·\s*组牌与对局并行\s*·\s*耗时\s*([\d.]+)\s*秒\s*·\s*正常完成的独立轮抓桌\s*(\d+)\s*桌。$/, (_,workers,seconds,pods) => `Up to ${workers} games in parallel · drafting and games overlapped · ${seconds} seconds · ${pods} independent draft pods with completed games.`],
    [/^Forge (.+?) · 组牌：(.+?) · (\d+) 局新运行 \/ (\d+) 局复用 · (\d+) 桌 · 每桌 (\d+) 局 · (\d+) 张(含指挥官|传统牌组) · (\d+) 点生命$/, (_,version,policy,run,reused,pods,games,cards,format,life) => `Forge ${version} · deck policy: ${translated(policy)} · ${run} new games / ${reused} reused · ${pods} pods · ${games} games per pod · ${cards} cards${format==='含指挥官'?' including commander':''} · ${life} starting life`],
    [/^(.+) 未运行的轮抓桌数：(\d+)。牌张支持 (\d+)\/(\d+)。未实现：(.+)。$/, (_,note,skipped,supported,total,missing) => `${translated(note)} Skipped pods: ${skipped}. Card support: ${supported}/${total}. Unsupported: ${missing==='无'?'none':missing}.`],
    [/^启发式评价：(.+)$/, (_,items) => `Heuristic scores: ${items}`],
    [/^([WUBRG]{1,5})\s*·\s*(牺牲|返场)$/, (_,g,theme) => `${g} · ${theme==='牺牲'?'Sacrifice':'Reanimator'}`],
    [/^独立\s*(\d+)\s*桌\s*\/\s*(\d+)\s*副牌组：结构均值\s*([\d.-]+)\s*→\s*([\d.-]+)；较弱牌组第10百分位\s*([\d.-]+)\s*→\s*([\d.-]+)；色组差\s*([\d.-]+)\s*→\s*([\d.-]+)。这些指标不是胜率。$/, (_,pods,decks,a,b,c,d,e,f) => `Independent sample: ${pods} pods / ${decks} decks. Structural mean: ${a} → ${b}; 10th percentile: ${c} → ${d}; color-pair gap: ${e} → ${f}. These metrics are not win rates.`],
    [/^训练\s*(\d+\/\d+)\s*局；旧版测试\s*(\d+\/\d+)\s*局；交叉\s*(\d+)\s*局，固定第三副牌并轮换座位。$/, (_,training,before,cross) => `Training: ${training} games; original-version tests: ${before} games; cross-play: ${cross} games with a fixed third deck and rotating seats.`],
    [/^(\d+)\s*张新版 CSV$/, (_,n) => `${n}-card revised Cube CSV`],
    [/^轮抓可用\s*(\d+)\s*次\s*\/\s*入组\s*(\d+)\s*次；训练实战\s*(\d+)\s*局\s*\/\s*施放\s*(\d+)\s*次$/, (_,available,included,games,casts) => `Drafted in ${available} pools / included in ${included} decks; ${games} training games / ${casts} casts`],
    [/^轮抓可用\s*(\d+)\s*次\s*\/\s*入组\s*(\d+)\s*次；暂无实战入组样本$/, (_,available,included) => `Drafted in ${available} pools / included in ${included} decks; no game sample yet`],
    [/^费用分布计入\s*(\d+)\s*张牌中识别到的附加法术力；部分费用可用其他资源支付。$/, (_,n) => `The curve includes additional mana costs detected on ${n} cards; some costs may be paid with other resources.`],
    [/^色组\s*(\S+)\s*的\s*(\S+)\s*回报缺少支持$/, (_,g,t) => `${g} ${t} payoffs lack support.`],
    [/^(\S+)\s*的\s*(\S+)\s*回报缺少支持$/, (_,g,t) => `${g} ${t} payoffs lack support.`],
    [/^参考来源为相同玩法的 Cube，当前\s*(\d+)\s*张牌在参考列表中出现过；名单只提供小幅选牌加分。$/, (_,n) => `Reference Cubes use the same format. ${n} cards appear in the reference lists; this provides only a small selection bonus.`]
  ];

  function translated(value) {
    const match = /^(\s*)(.*?)(\s*)$/s.exec(value);
    if (!match) return value;
    if (Object.prototype.hasOwnProperty.call(dictionary, match[2]))
      return match[1] + dictionary[match[2]] + match[3];
    for (const [pattern, render] of dynamicRules)
      if (pattern.test(match[2])) return match[1] + match[2].replace(pattern,render) + match[3];
    // Dynamic counts and card names occur between application-owned phrases.
    // Only substantial catalogued phrases are substituted; never translate
    // editable fields, card Oracle text, or user-authored AI responses.
    return match[1] + match[2].replace(fragments.regex, item => fragments.lookup[item]) + match[3];
  }

  function textNode(node) {
    const parent = node.parentElement;
    if (!parent || /^(SCRIPT|STYLE|TEXTAREA|PRE|CODE)$/.test(parent.tagName) ||
        parent.closest?.('.oracle, #knowledge-results, [data-user-content]')) return;
    if (parent.tagName === 'OPTION' && parent.value && parent.closest?.('#home-library, #runs, #examples')) return;
    const previous = originals.get(node);
    let original = previous && (node.nodeValue === previous.rendered || node.nodeValue === previous.original)
      ? previous.original : node.nodeValue;
    const rendered = language === 'en' ? translated(original) : (chinese[original.trim()] ?? original);
    if (rendered !== original && parent.tagName === 'OPTION' && !parent.hasAttribute('value')) {
      parent.setAttribute('value', original.trim());
    }
    originals.set(node, {original, rendered});
    if (node.nodeValue !== rendered) node.nodeValue = rendered;
  }

  function element(node) {
    if (node.tagName === 'A' && node.hasAttribute('href')) {
      const href = node.getAttribute('href');
      const report = /^(\/(?:exports|optimizations|matches|studies|diagnostics)\/[^/?#]+\/report\.md)(?:\?lang=en)?$/.exec(href);
      if (report) {
        const wanted = report[1] + (language === 'en' ? '?lang=en' : '');
        if (wanted !== href) node.setAttribute('href', wanted);
      }
    }
    let state = attributeOriginals.get(node) || {};
    for (const name of attributes) {
      if (!node.hasAttribute(name)) continue;
      const value = node.getAttribute(name);
      const previous = state[name];
      const original = previous && (value === previous.rendered || value === previous.original)
        ? previous.original : value;
      const rendered = language === 'en' ? translated(original) : (chinese[original.trim()] ?? original);
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

  function setLanguage(value, persist=true) {
    language = value === 'zh-CN' ? 'zh-CN' : 'en';
    selector.value = language;
    document.documentElement.lang = language;
    if (preview) preview.hidden = language !== 'en';
    if (persist) try { localStorage.setItem('cube-ui-language', language); } catch (_) { /* optional */ }
    visit(document.documentElement);
  }

  let userChanged = false;
  selector.addEventListener('change', () => { userChanged = true; setLanguage(selector.value); });
  new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData') visit(record.target);
      else if (record.type === 'attributes') element(record.target);
      else for (const node of record.addedNodes) visit(node);
    }
  }).observe(document.documentElement, {subtree: true, childList: true, characterData: true,
    attributes: true, attributeFilter: attributes});
  let initial = 'en';
  try { initial = localStorage.getItem('cube-ui-language') || initial; } catch (_) { /* optional */ }
  Promise.all(['/i18n_en.json','/i18n_machine_en.json'].map(url => fetch(url).then(response => {
    if (!response.ok) throw new Error('Translation dictionary unavailable');
    return response.json();
  }))).then(([reviewed,machine]) => {
    // Human-reviewed strings always take precedence over machine translations.
    const data = {...machine,...reviewed};
    dictionary = data;
    const keys = Object.keys(data).filter(k => (k.match(/[\u4e00-\u9fff]/g)||[]).length >= 4 &&
      !/[\r\n<>]/.test(k)).sort((a,b) => b.length-a.length);
    fragments = {lookup:data, regex: keys.length ? new RegExp(keys.map(k => k.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|'),'g') : /$^/g};
    setLanguage(userChanged ? language : initial);
  })
    .catch(() => { selector.disabled = true; setLanguage('zh-CN', false); });
  window.cubeI18n = {setLanguage};
})();
