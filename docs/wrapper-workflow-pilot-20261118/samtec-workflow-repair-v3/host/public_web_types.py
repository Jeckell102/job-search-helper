from html.parser import HTMLParser

class ToolError(ValueError):
    pass

class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.parts = []
        self.links = []
        self.anchor = None
    def handle_starttag(self, tag, attrs):
        if tag == 'a' and not self.depth and len(self.links) < 100:
            href = dict(attrs).get('href')
            self.anchor = {'url': href, 'text': ''} if isinstance(href, str) and len(href) <= 2048 else None
        if tag in ('script', 'style'):
            self.depth += 1
    def handle_endtag(self, tag):
        if tag == 'a' and self.anchor is not None:
            self.anchor['text'] = ' '.join(self.anchor['text'].split())[:250]
            self.links.append(self.anchor)
            self.anchor = None
        if tag in ('script', 'style') and self.depth:
            self.depth -= 1
    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)
            if self.anchor is not None:
                self.anchor['text'] = (self.anchor['text'] + ' ' + data)[:500]
