from pathlib import Path
import re,html
from markdown_it import MarkdownIt
ROOT=Path(__file__).resolve().parent
RELEASE_DATE=re.search(r'^APP_RELEASE_DATE = "([^"]+)"', (ROOT/'main.py').read_text(encoding='utf-8'), re.M).group(1)
MD=MarkdownIt('commonmark',{'html':False})
CSS="body{margin:0;background:#101820;color:#e5edf3;font:16px/1.65 system-ui,sans-serif}main{max-width:980px;margin:auto;padding:32px 24px 70px}h1,h2,h3{line-height:1.25;color:#fff}h2{margin-top:2.3em;border-bottom:1px solid #405361;padding-bottom:10px;scroll-margin-top:18px}a{color:#79c9ff}code{background:#243441;padding:2px 5px;border-radius:3px}li{margin:.5em 0}nav{padding:18px 24px;background:#1a2b38;border:1px solid #405361;border-radius:10px}nav ul{columns:2;padding-left:20px}nav li{break-inside:avoid}p,li{overflow-wrap:anywhere}@media(max-width:600px){nav ul{columns:1}main{padding:18px}}"
def render(text):
    tokens=MD.parse(text);toc=[]
    for i,t in enumerate(tokens):
        if t.type=='heading_open' and t.tag=='h2':
            label=tokens[i+1].content
            slug=re.sub(r'[^a-z0-9]+','-',label.lower()).strip('-')
            t.attrSet('id',slug);toc.append((slug,label))
    content=MD.renderer.render(tokens,MD.options,{})
    for name in ['PUBLIC_HOSTING','DEVELOPMENT_MODEM','linux-raspberry-pi','docker','CROSS_PLATFORM_SETUP']:
        content=content.replace('href="'+name+'.md"','href="/static/guides/'+name+'.html"').replace('href="docs/'+name+'.md"','href="/static/guides/'+name+'.html"')
    return content,toc

def page(title,body,toc):
    nav='<nav aria-label="Contents"><strong>Contents</strong><ul>'+''.join('<li><a href="#'+slug+'">'+html.escape(label)+'</a></li>' for slug,label in toc)+'</ul></nav>'
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title><style>'+CSS+'</style></head><body><main>'+nav+body+'<p><a href="/static/documentation.html">Full user guide</a> &#183; <a href="/">Dashboard</a></p></main></body></html>'

text=(ROOT/'docs/USER_GUIDE.md').read_text(encoding='utf-8')
body,toc=render(text)
(ROOT/'static/documentation.html').write_text(page('APRS PropView User Guide',body,toc),encoding='utf-8')
help_body=re.sub(r'<(/?)h([123])([^>]*)>',lambda m:'<'+m[1]+'h'+str({'1':3,'2':3,'3':4}[m[2]])+m[3]+'>',body)
# Scope anchors inside the modal so they do not conflict with the main dashboard.
help_body=re.sub(r'id="([^"]+)"',r'id="help-guide-\1"',help_body)
help_body='<p><button id="btn-help-quick-start" class="btn-primary">Open Illustrated Quick Start</button> <a href="/static/documentation.html" target="_blank" rel="noopener">Open full documentation</a></p>'+help_body
index=ROOT/'static/index.html';source=index.read_text(encoding='utf-8')
start=source.index('            <div class="help-body">')+len('            <div class="help-body">')
end=source.index('\n            </div>\n        </div>\n    </div>\n\n    <!--',start)
updated_index=source[:start]+'\n'+help_body+source[end:]
updated_index=re.sub(r'(<span id="about-date">)[^<]*(</span>)',lambda match:match[1]+html.escape(RELEASE_DATE)+match[2],updated_index)
index.write_text(updated_index,encoding='utf-8')
folder=ROOT/'static/guides';folder.mkdir(exist_ok=True)
for name in ['PUBLIC_HOSTING','DEVELOPMENT_MODEM','linux-raspberry-pi','docker','CROSS_PLATFORM_SETUP']:
    content,headings=render((ROOT/('docs/'+name+'.md')).read_text(encoding='utf-8'))
    (folder/(name+'.html')).write_text(page(name.replace('_',' '),content,headings),encoding='utf-8')
print('Generated full documentation, in-app help and four companion guides')

releases=ROOT/'static/releases';releases.mkdir(exist_ok=True)
release_body,release_toc=render((ROOT/'CHANGELOG.md').read_text(encoding='utf-8'))
version = re.search(r'^APP_VERSION = "([^"]+)"', (ROOT/'main.py').read_text(encoding='utf-8'), re.M).group(1)
(releases/('v'+version+'.html')).write_text(page('APRS PropView '+version+' changelog',release_body,release_toc),encoding='utf-8')
