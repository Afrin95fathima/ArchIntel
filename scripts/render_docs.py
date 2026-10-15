"""Build portable HTML manuals from the maintained Markdown sources."""
from pathlib import Path
import markdown

ROOT = Path(__file__).resolve().parents[1]
STYLE = """
@page { size: A4; margin: 19mm 17mm; }
body { font: 14px/1.65 Arial, sans-serif; color: #24332e; max-width: 900px; margin: 40px auto; padding: 0 24px; }
h1 { font-size: 32px; color: #125a43; line-height: 1.2; border-bottom: 3px solid #168561; padding-bottom: 18px; }
h2 { font-size: 21px; color: #125a43; margin-top: 32px; }
h3 { font-size: 16px; margin-top: 24px; }
h1,h2,h3 { break-after: avoid; }
a { color: #12664c; overflow-wrap: anywhere; }
pre { background: #eff4f1; padding: 14px; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11px; }
code { font-size: 0.9em; background: #eff4f1; }
table { border-collapse: collapse; width: 100%; font-size: 12px; }
td,th { padding: 8px; border: 1px solid #d6dfda; text-align: left; overflow-wrap: anywhere; }
th { background: #eff4f1; }
tr, img { break-inside: avoid; }
img { max-width: 100%; }
blockquote { border-left: 3px solid #168561; padding-left: 15px; }
.edition { text-transform: uppercase; font-size: 11px; letter-spacing: 1px; color: #63786e; }
@media print { body { margin: 0; padding: 0; font-size: 11px; max-width: none; } h1 { font-size: 27px; } h2 { font-size: 18px; } pre { font-size: 9px; } table { font-size: 9px; } }
"""
for name in ('USER-MANUAL', 'DEVELOPER-GUIDE', 'RUNTIME-USER-FLOW', 'RUNTIME-DEVELOPER-GUIDE', 'PHASE-1-USER-FLOW', 'PHASE-1-DEVELOPER-GUIDE', 'PHASE-2-USER-FLOW', 'PHASE-2-DEVELOPER-GUIDE', 'PHASE-3-USER-FLOW', 'PHASE-3-DEVELOPER-GUIDE', 'PHASE-4-USER-FLOW', 'PHASE-4-DEVELOPER-GUIDE', 'PHASE-5-USER-FLOW', 'PHASE-5-DEVELOPER-GUIDE', 'PHASE-6-USER-FLOW', 'PHASE-6-DEVELOPER-GUIDE', 'PHASE-7-USER-FLOW', 'PHASE-7-DEVELOPER-GUIDE', 'PHASE-8-USER-FLOW', 'PHASE-8-DEVELOPER-GUIDE', 'PHASE-9-USER-FLOW', 'PHASE-9-DEVELOPER-GUIDE'):
    source = ROOT / 'docs' / f'{name}.md'
    body = markdown.markdown(source.read_text(encoding='utf-8-sig'), extensions=['tables', 'fenced_code', 'toc'])
    page = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>ArchIntel {name}</title><style>{STYLE}</style></head><body><div class="edition">ArchIntel · Investor prototype · 5 October 2026</div>{body}</body></html>'
    source.with_suffix('.html').write_text(page, encoding='utf-8')
    print(f'Generated docs/{name}.html')
