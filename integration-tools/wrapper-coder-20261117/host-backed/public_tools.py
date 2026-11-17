"""Host execution for the coding profile's public read-only web tools."""
import public_web
import rendered_web
NAMES = {'web_read', 'web_search', 'rendered_web_read'}

def execute(name, args, names):
    try:
        if name not in NAMES or name not in names:
            raise ValueError('This action is outside the current request.')
        key = 'url' if name in ('web_read', 'rendered_web_read') else 'query'
        if not isinstance(args, dict) or set(args) != {key} or not isinstance(args[key], str):
            raise ValueError('Invalid web tool arguments.')
        if name == 'rendered_web_read':
            result = rendered_web.read_page(args[key])
        else:
            result = public_web.read_page(args[key]) if name == 'web_read' else public_web.search(args[key])
        return {'ok': True, 'result': result, 'execution_location': 'scraper computer'}
    except (ValueError, OSError, TimeoutError, public_web.http.client.HTTPException) as exc:
        return {'ok': False, 'error': str(exc)[:350], 'execution_location': 'scraper computer'}
