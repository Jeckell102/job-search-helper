"""Range-aware offline Sheets API. Never authenticates or contacts a service."""
import copy
import json
import re
from test_batching import StatefulSheets


def column(text):
    result = 0
    for letter in text:
        result = result * 26 + ord(letter) - 64
    return result - 1


class RangeSheets(StatefulSheets):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.response_bytes = 0
        self.request_bytes = 0
        self.lose_response = False
        self.before_write = None
        self.before_read = None

    def get(self, **kwargs):
        self.get_calls.append(copy.deepcopy(kwargs))
        outer = self
        class Response:
            def execute(self, num_retries=0):
                if outer.before_read:
                    outer.before_read(kwargs)
                result = []
                for source in outer.sheets:
                    title = source['properties']['title']
                    requested = [r.split('!', 1)[1] for r in kwargs.get('ranges', [])
                                 if r.split('!', 1)[0].strip("'") == title]
                    if kwargs.get('ranges') and not requested:
                        continue
                    sheet = {key: copy.deepcopy(source[key]) for key in ('properties', 'tables')}
                    if kwargs.get('includeGridData'):
                        sheet['data'] = []
                        for area in requested:
                            first, last = area.split(':') if ':' in area else (area, area)
                            a = re.fullmatch(r'([A-Z]*)(\d*)', first)
                            b = re.fullmatch(r'([A-Z]*)(\d*)', last)
                            c0 = column(a[1]) if a[1] else 0
                            c1 = column(b[1]) + 1 if b[1] else source['properties']['gridProperties']['columnCount']
                            r0 = int(a[2]) - 1 if a[2] else 0
                            r1 = int(b[2]) if b[2] else source['properties']['gridProperties']['rowCount']
                            raw_rows = source['data'][0]['rowData']
                            rows = [{'values': copy.deepcopy(row.get('values', [])[c0:c1])}
                                    for row in raw_rows[r0:r1]]
                            sheet['data'].append({'startRow': r0, 'startColumn': c0, 'rowData': rows})
                    result.append(sheet)
                response = {'sheets': result}
                outer.response_bytes += len(json.dumps(response, ensure_ascii=True).encode())
                return response
        return Response()

    def batchUpdate(self, **kwargs):
        outer = self
        self.request_bytes += len(json.dumps(kwargs['body'], ensure_ascii=True).encode())
        response = super().batchUpdate(**kwargs)
        class Response:
            def execute(self):
                if outer.before_write:
                    outer.before_write()
                result = response.execute()
                if outer.lose_response:
                    outer.lose_response = False
                    raise TimeoutError('applied, response lost')
                return result
        return Response()

    def set_cell(self, tab, row, header, value=None, cell=None):
        sheet = self.sheet(tab)
        rows = sheet['data'][0]['rowData']
        while len(rows) <= row:
            rows.append({'values': []})
        cells = rows[row]['values']
        col = self.schemas[tab].index(header)
        while len(cells) <= col:
            cells.append({})
        cells[col] = cell if cell is not None else {'userEnteredValue': {'stringValue': value},
                                                   'effectiveValue': {'stringValue': value}}

    def values(self):
        outer = self
        class Values:
            def _response(self, ranges, single=False):
                grid = outer.get(ranges=ranges, includeGridData=True)
                class Response:
                    def execute(self, num_retries=0):
                        before_bytes = outer.response_bytes
                        data = grid.execute(num_retries=num_retries)
                        by_title = {s['properties']['title']: s for s in data['sheets']}
                        offsets = {}
                        results = []
                        for area in ranges:
                            title = area.split('!', 1)[0].strip("'")
                            offset = offsets.get(title, 0)
                            block = by_title[title]['data'][offset]
                            offsets[title] = offset + 1
                            rows = []
                            for row in block.get('rowData', []):
                                values = []
                                for cell in row.get('values', []):
                                    value = cell.get('effectiveValue', cell.get('userEnteredValue', {}))
                                    values.append(next(iter(value.values()), ''))
                                while values and values[-1] == '':
                                    values.pop()
                                rows.append(values)
                            while rows and not rows[-1]:
                                rows.pop()
                            results.append({'range': area, 'values': rows})
                        response = results[0] if single else {'valueRanges': results}
                        outer.response_bytes = before_bytes + len(json.dumps(response, ensure_ascii=True).encode())
                        return response
                return Response()
            def get(self, **kwargs):
                return self._response([kwargs['range']], single=True)
            def batchGet(self, **kwargs):
                return self._response(kwargs['ranges'])
        return Values()
