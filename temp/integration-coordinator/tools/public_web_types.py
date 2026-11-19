from html.parser import HTMLParser
import re

class ToolError(ValueError):
    pass

class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.parts = []
        self.links = []
        self.anchor = None
        self.classes = set()
        self.ids = set()
        self.forms = []
        self.pagination = []
        self.structure_truncated = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if not self.depth:
            for field, values in (('class', self.classes), ('id', self.ids)):
                for value in (a.get(field) or '').split():
                    if len(value) > 128 or len(values) >= 512:
                        self.structure_truncated = True
                    else:
                        values.add(value)
            if tag == 'form':
                if len(self.forms) < 20:
                    self.forms.append({'action': (a.get('action') or '')[:2049],
                                       'method': (a.get('method') or 'GET').upper()[:20]})
                else:
                    self.structure_truncated = True
            if tag == 'a':
                href = a.get('href')
                self.anchor = ({'url': href, 'text': '', 'rel': (a.get('rel') or '')[:100],
                                'aria_label': (a.get('aria-label') or '')[:250],
                                'class': (a.get('class') or '')[:250]}
                               if isinstance(href, str) and len(href) <= 2048 else None)
        if tag in ('script', 'style'):
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == 'a' and self.anchor is not None:
            self.anchor['text'] = ' '.join(self.anchor['text'].split())[:250]
            if len(self.links) < 100:
                self.links.append({k:self.anchor[k] for k in ('url','text')})
            candidate = ' '.join(str(self.anchor[k]) for k in ('rel','aria_label','class','text','url'))
            if re.search(r'\b(next|previous|prev|pagination|paginate)\b|[?&]page(?:number|index)?=', candidate, re.I):
                if len(self.pagination) < 32:
                    self.pagination.append(self.anchor.copy())
                else:
                    self.structure_truncated = True
            self.anchor = None
        if tag in ('script', 'style') and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)
            if self.anchor is not None:
                self.anchor['text'] = (self.anchor['text'] + ' ' + data)[:500]

    def structure(self, input_truncated=False):
        def priority(value):
            return (not bool(re.search(r'job|list|search|pagin|next', value, re.I)), value)
        classes = sorted(self.classes, key=priority)
        ids = sorted(self.ids, key=priority)
        truncated = bool(input_truncated or self.structure_truncated or len(classes)>128 or len(ids)>128)
        return {'kind':'source_html_attributes', 'classes':classes[:128], 'ids':ids[:128],
                'forms':self.forms, 'pagination':self.pagination,
                'complete':not truncated, 'truncated':truncated,
                'verified_inventory':False,
                'warning':'Untrusted source HTML attributes, not rendered DOM. Truncated structure cannot prove absence; structure never proves complete job inventory.'}
