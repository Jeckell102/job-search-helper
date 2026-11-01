"""MARTAC's public, static careers table."""
from hashlib import sha256
from html.parser import HTMLParser
from .ats import FetchError,Inventory,_base,text
from .discovery import CareersTransport

SOURCE='https://martacsystems.com/careers/'
TABLE='eael-data-table-037568c'

class Parser(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True);self.table=self.row=self.cell=False;self.rows=[];self.cells=[];self.parts=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='table' and a.get('id')==TABLE:self.table=True
  elif self.table and tag=='tr':self.row=True;self.cells=[]
  elif self.row and tag in ('td','th'):self.cell=True;self.parts=[]
 def handle_data(self,data):
  if self.cell:self.parts.append(data)
 def handle_endtag(self,tag):
  if self.cell and tag in ('td','th'):self.cells.append(' '.join(''.join(self.parts).split()));self.cell=False
  elif self.table and tag=='tr':
   if self.cells:self.rows.append(self.cells)
   self.row=False
  elif self.table and tag=='table':self.table=False

def listing(t):
 r=t.get(SOURCE)
 if r.status!=200:raise FetchError('blocked' if r.status in (401,403,429) else 'partial','MARTAC careers page was unavailable.')
 try:p=Parser();p.feed(r.body.decode());p.close()
 except (UnicodeDecodeError,ValueError):raise FetchError('partial','MARTAC careers table could not be parsed.') from None
 rows=p.rows
 if not rows or rows[0]!=['Job Title','Job Description'] or not (1<=len(rows)-1<=200) or any(len(x)!=2 or not all(x) for x in rows[1:]):raise FetchError('partial','MARTAC positions table is missing or incomplete.')
 return rows[1:]

def fetch_martac(url,cid,company,transport=None):
 if url!=SOURCE:return Inventory('unsupported',reason='MARTAC adapter requires its verified unfiltered careers page.',source_url=url,ats='Static careers page')
 jobs=[]
 try:
  rows=listing(transport or CareersTransport());seen=set()
  for title,description in rows:
   ident=sha256(title.casefold().encode()).hexdigest()[:24]
   if ident in seen:raise FetchError('partial','MARTAC positions table has duplicate titles.')
   seen.add(ident);row=_base({'id':ident},'Static careers page',cid,company);row.update(title=text(title),description=text(description),url=SOURCE);jobs.append(row)
  if listing(transport or CareersTransport())!=rows:raise FetchError('partial','MARTAC positions changed during the scan.')
  return Inventory('complete',jobs,f'MARTAC: retrieved {len(jobs)} published positions and rechecked the careers table.',SOURCE,'Static careers page')
 except FetchError as e:return Inventory(e.status,jobs,e.reason,SOURCE,'Static careers page')
 except (AttributeError,TypeError,ValueError):return Inventory('partial',jobs,'MARTAC positions schema validation failed.',SOURCE,'Static careers page')
