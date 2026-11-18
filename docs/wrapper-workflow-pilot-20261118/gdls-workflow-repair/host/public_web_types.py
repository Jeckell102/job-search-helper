from html.parser import HTMLParser

class ToolError(ValueError):
    pass

class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.depth += 1
    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.depth:
            self.depth -= 1
    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)
