"""Independent saved-source parser; no adapter imports or network."""
from html.parser import HTMLParser
from urllib.parse import urljoin

class PublicDetail(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.matches={key:[] for key in ('description','title','location','employer','position_employer')}
        self.active=[];self.apply=[];self.ignored=0
        self.feed(body);self.close()
        if self.active:raise ValueError('Unclosed public detail evidence element')
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in {'script','style'}:self.ignored+=1
        if self.ignored:return
        classes=set(a.get('class','').split())
        if tag in {'p','div','br','li','h1','h2','h3','h4','h5','h6','tr','td'}:
            for item in self.active:item['text'].append('\n')
        if tag=='span' and 'jv-inline-separator' in classes:
            for item in self.active:
                if item.get('kind')=='location':item['text'].append('\x1f')
        for item in self.active:
            if item['tag']==tag:item['depth']+=1
        key=None
        if tag=='div' and 'jv-job-detail-description' in classes:key='description'
        elif tag=='div' and 'jv-meta' in classes and any(i.get('kind')=='description' for i in self.active):key='position_employer'
        elif tag=='h2' and 'jv-header' in classes:key='title'
        elif tag=='p' and 'jv-job-detail-meta' in classes:key='location'
        elif tag=='h1' and 'jv-logo' in classes:key='employer'
        if key:
            item={'tag':tag,'depth':1,'text':[],'kind':key};self.matches[key].append(item);self.active.append(item)
        if tag=='a' and 'jv-button-apply' in classes:self.apply.append(a.get('href',''))
    def handle_endtag(self,tag):
        if tag in {'script','style'} and self.ignored:self.ignored-=1;return
        if self.ignored:return
        if tag in {'p','div','li','h1','h2','h3','h4','h5','h6','tr','td'}:
            for item in self.active:item['text'].append('\n')
        for item in list(self.active):
            if item['tag']==tag:
                item['depth']-=1
                if item['depth']==0:self.active.remove(item)
    def handle_data(self,data):
        if not self.ignored:
            for item in self.active:item['text'].append(data)
    def value(self,key):
        values=self.matches[key]
        if len(values)!=1:raise ValueError('Public '+key+' is not unique')
        return ' '.join(''.join(values[0]['text']).split())

def detail_evidence(body,url):
    p=PublicDetail(body)
    result={k:p.value(k) for k in p.matches}
    if 'samtec' not in result['employer'].casefold() or result['position_employer']!='Position at Samtec, Inc':raise ValueError('Public employer differs')
    targets=[urljoin(url,v) for v in p.apply]
    if not targets or any(v!=url+'/apply' for v in targets):raise ValueError('Public application identity differs')
    if len(result['description'])<120 or not result['title'] or not result['location']:raise ValueError('Incomplete public detail')
    meta=p.matches['location'][0]['text']
    pieces=''.join(meta).split('\x1f')
    if len(pieces)<2 or any(not v.strip() for v in pieces):raise ValueError('Public department/location separator ambiguous')
    result['department']=' '.join(pieces[0].split())
    result['location']='; '.join(' '.join(v.split()) for v in pieces[1:])
    result['apply_targets']=targets
    return result
