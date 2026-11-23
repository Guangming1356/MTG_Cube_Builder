"""Offline UI/report translations; never sends a user's data to a service."""
import json
import re
from functools import lru_cache
from .config import ROOT


@lru_cache(maxsize=1)
def catalog():
    base=ROOT/'web'
    automatic=json.loads((base/'i18n_machine_en.json').read_text(encoding='utf8'))
    reviewed=json.loads((base/'i18n_en.json').read_text(encoding='utf8'))
    automatic.update(reviewed)
    keys=[k for k in automatic if len(re.findall('[\u4e00-\u9fff]',k))>=4 and not re.search('[\r\n<>]',k)]
    pattern=re.compile('|'.join(re.escape(k) for k in sorted(keys,key=len,reverse=True))) if keys else re.compile(r'(?!)')
    return automatic,pattern


def translate_text(value):
    """Translate known application phrases, retaining unknown content and numbers."""
    data,pattern=catalog()
    if value in data:return data[value]
    stripped=value.strip()
    if stripped in data:
        left=len(value)-len(value.lstrip());right=len(value)-len(value.rstrip())
        return value[:left]+data[stripped]+(value[len(value)-right:] if right else '')
    return pattern.sub(lambda m:data[m.group()],value)


def report_english(text):
    """Translate report prose without changing headings naming a Cube or code/URLs.

    The first heading can be a user-defined Cube name; fenced and inline code
    and link targets are preserved. Unknown text is kept, rather than guessed.
    """
    protected=re.compile(r'(`[^`]*`|https?://[^\s)]+)')
    lines=text.splitlines(keepends=True);in_code=False;out=[]
    for index,line in enumerate(lines):
        if line.lstrip().startswith('```'):
            in_code=not in_code;out.append(line);continue
        if in_code or (index==0 and line.startswith('# ')):
            out.append(line);continue
        out.append(''.join(part if i%2 else translate_text(part) for i,part in enumerate(protected.split(line))))
    return ''.join(out)


def _report_data(value):
    if isinstance(value,dict):return {k:_report_data(v) for k,v in value.items()}
    if isinstance(value,list):return [_report_data(v) for v in value]
    if isinstance(value,str):return translate_text(value)
    return value


def audit_report_english(result):
    """Render the saved structured audit with stable English labels and values."""
    audit=result['audit'];spec=result['spec']
    lines=[f"# {spec['name']}",'',f"Cards: {audit['total']}; slots: {audit['roles']}; hard errors: {audit['hard_errors']}.",
           '',f"Card snapshot: {audit['snapshot']}. Card scores are heuristics, not observed win rates.",
           '','## Main-deck mana curve','',str(audit['curve']),'','## Role density','',str(audit['role_counts']),
           '','## Audit findings','']
    for issue in audit['issues']:
        message=issue['message']
        match=re.fullmatch(r'(\w+) 的 (\w+) 回报缺少支持',message)
        if match:message=f'{match[1]} {match[2]} payoffs lack support.'
        else:message=translate_text(message)
        names=', '.join(issue.get('cards',[]))
        lines.append(f"- [{issue['severity']}] {message}"+(f' ({names})' if names else ''))
    if not audit['issues']:lines.append('No issues found by the current checker.')
    if audit.get('bracket'):
        b=audit['bracket'];limit=b['official_deck_gc_limit']
        lines.extend(['','## Commander Bracket target','',
            f"Target: {b['target']} ({b['name'].split('·')[0].strip()}); reviewed: {b['reviewed']}; policy: {b['version']}.",
            f"Project main-deck mean: {b['main_mean']}; band: {b['project_mean_band']}; high-rated main-deck cards: {b['high_quality_main']}/{b['project_high_quality_limit']}.",
            f"Cube Game Changers: {len(b['game_changers'])}/{b['cube_gc_limit']}; official deck limit: {limit if limit is not None else 'unlimited'} (including commander and lands).",
            translate_text(b['limitation']),'','Official sources:',*['- '+url for url in b['sources']]])
    if audit.get('design'):
        d=audit['design'];lines.extend(['','## Design checks','',
            f"Policy: {d['version']}; research: {d['study_version']}; cards appearing in comparable reference Cubes: {d['reference_count']}.",
            '',translate_text(d['limitation']),''])
        for guild,packages in d['guild_packages'].items():
            for name,p in packages.items():
                if p['active']:
                    components=' / '.join(f"{translate_text(v['label'])}: {v['count']}" for v in p['components'].values())
                    lines.append(f"- {guild} {name}: {components}; {translate_text(p['status'])}.")
    return '\n'.join(lines)+'\n'


def match_report_english(result):
    """Render the game summary and game log links from the saved match."""
    summary=result['summary'];rules=result['rules'];coverage=result['coverage']
    lines=['# Forge match report','',f"Engine: Forge {result['engine']['version']} (native AI).",
        f"Draft: {result['pods']} pods; {result['games_per_pod']} games per pod, rotating seats.",
        f"Decks: {rules['deck_total_exported']} cards; starting life: {rules['starting_life']}.",
        f"Completed normally: {summary['completed']}/{len(result['games'])} games.",
        f"Outcomes: {json.dumps(summary['outcomes'],ensure_ascii=False,sort_keys=True)}.",
        f"Skipped draft pods: {result['skipped_pods']}; engine card coverage: {coverage['supported']}/{coverage['total']}.",
        *([f"Skipped pairings involving unsupported decks: {result['skipped_games']}."] if 'skipped_games' in result else []),
        '',('Results reflect the specific drafting, deck-building, and Forge AI strategies. '
            'Small samples do not establish color balance or human win rates. Engine failures and timeouts are excluded from ordinary results.'),
        '','## Game records','']
    for game in result['games']:
        log=game['log'];winner=game.get('winner') or 'none';turns=game.get('turns')
        lines.append(f"- Pod {game['pod']+1}, game {game['game']+1}: {game['outcome']}; winner: {winner}; turns: {turns if turns is not None else 'unknown'}; [log]({log})")
    return '\n'.join(lines)+'\n'


def optimization_report_english(result):
    """Render the decision, measured outcomes, gates, and each proposed swap."""
    s=result['structural'];t=result['training'];cross=result['cross']
    lines=['# Forge feedback optimization report','',f"Status: {result['status']}; proposed swaps: {len(result['swaps'])}.",
        f"Training games completed: {t['completed']}/{t['attempted']}.",
        '', '## Structural results (not win rates)','',
        f"Mean: {s['mean_before']:.6f} → {s['mean_after']:.6f}; 10th percentile: {s['p10_before']:.6f} → {s['p10_after']:.6f}; color-pair gap: {s['gap_before']:.6f} → {s['gap_after']:.6f}.",
        f"Pod bootstrap 95% interval: {s.get('pod_bootstrap95')}.",
        '', '## Match results','',
        f"Before: {json.dumps(result['forge_before'],ensure_ascii=False,sort_keys=True)}.",
        f"After: {json.dumps(result['forge_after'],ensure_ascii=False,sort_keys=True)}.",
        f"Cross-play: {json.dumps(cross,ensure_ascii=False,sort_keys=True)}.",
        f"Behavior comparison: {json.dumps(_report_data(result.get('behavior',{})),ensure_ascii=False,sort_keys=True)}.",
        f"Sampling: {json.dumps(_report_data(result.get('sampling',{})),ensure_ascii=False,sort_keys=True)}.",
        f"Budget: {json.dumps(_report_data(result.get('budget',{})),ensure_ascii=False,sort_keys=True)}.",
        '', '## Acceptance gates','']
    lines.extend(f"- {key}: {'passed' if value else 'not passed'}" for key,value in result['gates'].items())
    lines.extend(['', '## Interpretation','',
        ('The candidate is provisional and requires more independent pods.' if result['status']=='provisional' else 'This is an experimental candidate; not all acceptance gates passed.'),
        'Structural metrics use automated drafts and heuristic features. Forge matches use its native AI; these results do not prove color balance, fun, or human win rates.',
        '', '## Proposed swaps',''])
    for swap in result['swaps']:
        lines.append(f"- {swap['remove']} → **{swap['add']}** ({swap['identity']}): {translate_text(swap.get('reason',''))}")
    return '\n'.join(lines)+'\n'


def study_report_english(result):
    summary=result['summary'];pods=result['pods']
    lines=['# Deck-building policy comparison','',
        f'Draft pods: {pods}; three games per pod and policy, rotating seats. The Cube was not changed.','',
        '| Policy | Completed / planned | Zero-action rate in first four complete cycles | Players casting a finisher |',
        '|---|---:|---:|---:|']
    def percent(value):return 'not recorded' if value is None else f'{value:.1%}'
    for policy,label in [('quality','Card quality first'),('balanced','Balanced curve (experimental)')]:
        item=summary['policies'][policy]
        lines.append(f"| {label} | {item['normal']}/{pods*3} | {percent(item['no_action_cycle_rate'])} | {percent(item['finisher_presence'])} |")
    lines.extend(['',f"Complete paired draft pods: {summary['paired_complete_pods']}.",
        'Observed data supports improved early action.' if summary['supports_activity_improvement'] else 'The current evidence does not establish improved early action; the default policy remains unchanged.',
        '',('A complete personal-turn cycle runs from the start of a player’s turn to the start of their next turn. '
            'It counts spells, activated abilities and attacks, but not automatic triggers or land plays.'),
        '',('Pod-paired intervals are descriptive. Incomplete games count towards the completion rate. '
            'A small Forge comparison does not establish human enjoyment, color balance, or general win rates.')])
    return '\n'.join(lines)+'\n'


def diagnostic_report_english(result):
    if not result['distinct_entries']:
        interpretation='The two entry points could not be compared independently; inspect the startup logs.'
    elif result['reproduced_both']:
        interpretation='Both entry points reproduced the original error symptoms. This supports an engine or AI issue but does not identify a card or prove a fix.'
    elif all(g['outcome'] in {'win','draw'} for g in result['games']):
        interpretation='Both entry points completed normally. This run did not reproduce the issue and does not prove it is fixed.'
    else:
        interpretation='The entry points reproduced different symptoms. Further log analysis is required; diagnostic wins and losses are not evidence of card strength.'
    lines=['# Game engine entry-point diagnostic','',interpretation,'',
        f"The same deck files, seat order and seed are used for one game at each entry point, with a {result['clock_seconds']}-second limit. Match caches are not reused.",'']
    for game in result['games']:
        lines.append(f"- {game['requested_backend']}: {game['outcome']}; log: {game['log']}.")
        lines.extend('  - '+translate_text(finding['message']) for finding in game.get('diagnostics',[]))
    lines.extend(['','This diagnoses a known case, not card strength. It does not modify the original match, decks, or Cube, and does not automatically exclude cards.'])
    if not result.get('original_deck_hashes_verified'):
        lines.append('Some original deck hashes are unavailable; the copied files cannot be verified as unchanged.')
    return '\n'.join(lines)+'\n'
