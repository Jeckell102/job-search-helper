"""A measured one-tool read projection for immutable historical guards."""
from hashlib import sha256
from pathlib import Path
import stat
from types import MethodType, FunctionType

RELATIVE = 'dev/wrapper-coder/tools/embraer_operator_pilot.py'
BEFORE = '28894e55d6c367fdda5813694c30efc3974c7844be6963dcd33fac88f60cad2e'
AFTER = '9669ae6860acff34c24af4164f4fe7e5b859da53dd8187045befb97a85d1e41a'


def reference(path):
    s=path.stat()
    return [s.st_dev,s.st_ino,stat.S_IMODE(s.st_mode),s.st_uid,s.st_gid,sha256(path.read_bytes()).hexdigest(),s.st_mtime_ns]


class Projection:
    def __init__(self, project, archived, original_endpoint, original_owner, authority, forward):
        self.project,self.archived=Path(project),Path(archived)
        self.endpoint,self.owner=original_endpoint,original_owner
        self.authority,self.forward=authority,forward

    def verify(self):
        for path in (self.project/RELATIVE,self.archived):
            if path.resolve(strict=True)!=path or not path.is_file() or path.stat().st_nlink!=1:
                raise ValueError('Tool projection requires physical exact files')
        archived=reference(self.archived); actual=reference(self.project/RELATIVE)
        if (archived[5]!=BEFORE or archived[2]!=self.endpoint['mode']
                or self.archived.stat().st_size!=self.endpoint['size'] or archived[3:5]!=self.owner
                or self.endpoint['sha256']!=BEFORE or actual[2]!=self.endpoint['mode'] or actual[3:5]!=self.owner):
            raise ValueError('Projected original endpoint or current metadata differs')
        intent=self.authority.get('intent'); receipt=self.authority.get('receipt')
        if actual[5]==AFTER:
            if intent is None:
                raise ValueError('Updated helper has no exact owned transition')
            self.forward.transition_record(intent)
            if intent['before_reference'][2:6] != [*actual[2:5],BEFORE]:
                raise ValueError('Current helper ownership differs from transition')
        elif actual[5]!=BEFORE:
            raise ValueError('Helper changed outside exact transition')
        if receipt is not None:
            expected=AFTER if receipt.get('status')=='INSTALLED' else BEFORE if receipt.get('status')=='ROLLED_BACK' else None
            if (actual!=receipt.get('current_reference') or actual[5]!=expected
                    or receipt.get('transition')!=intent):
                raise ValueError('Helper differs from terminal receipt')
        return actual

    def path(self):
        projection=self
        class ProjectedPath(type(Path())):
            def __truediv__(self, name):
                actual=Path(str(self))/name
                if actual==projection.project/RELATIVE:
                    projection.verify()
                    return projection.archived
                return actual
        return ProjectedPath(self.project)

    def wrap_owner(self, owner):
        # Original status code, original spec and complete runtime checks stay
        # intact; only the one independently measured pathname is projected.
        clone=type(owner).__new__(type(owner)); clone.__dict__.update(owner.__dict__)
        clone.project=self.path()
        return clone

    def wrap_window(self, window):
        projection=self
        original=window._lineage.__func__
        projected=FunctionType(original.__code__,{**original.__globals__,'PROJECT':self.path()},
                               original.__name__,original.__defaults__,original.__closure__)
        projected.__kwdefaults__=original.__kwdefaults__
        def lineage(this,*args,**kwargs):
            projection.verify()
            result=projected(this,*args,**kwargs)
            projection.verify()
            return result
        window._lineage=MethodType(lineage,window)
        window.source_owner=self.wrap_owner(window.source_owner)
        return window
