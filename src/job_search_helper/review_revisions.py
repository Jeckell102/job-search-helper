"""Transactional invalidation for review inputs, including non-repository writers.

Queue removals caused by completed reviews are fenced by fresh sheet controls.
Newly eligible rows, changed evidence and policy inputs require a new export.
"""
import uuid


def install(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='review_input_revisions'").fetchone():
        return
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS review_input_revisions '
                   '(id INTEGER PRIMARY KEY CHECK(id=1), epoch TEXT NOT NULL, queue INTEGER NOT NULL, controls INTEGER NOT NULL)')
        db.execute('INSERT OR IGNORE INTO review_input_revisions VALUES(1,?,0,0)', (uuid.uuid4().hex,))
        def projection(prefix, fields):
            return 'json_array(' + ','.join(
                f"json_extract({prefix}.data,'$.\"{field}\"')" for field in fields) + ')'
        history = ('Job Key', 'Source Hash', 'Job Title', 'Salary / Range',
                   'Official Job URL', 'Job Status', 'Reconsideration Status')
        evidence = ('Job Key', 'Source Hash', 'Job Description')
        def eligible(prefix):
            return (f"lower(trim(COALESCE(json_extract({prefix}.data,'$.\"Added to Opportunities?\"'),'')))='pending' AND "
                    f"lower(trim(COALESCE(json_extract({prefix}.data,'$.\"Review Status\"'),'')))='needs review'")
        changed = (f"OLD.tab IS NOT NEW.tab OR OLD.row_id IS NOT NEW.row_id OR "
                   f"(NEW.tab='Job History' AND ({projection('OLD', history)} IS NOT {projection('NEW', history)} "
                   f"OR (NOT ({eligible('OLD')}) AND ({eligible('NEW')})))) OR "
                   f"(NEW.tab='Job Evidence' AND {projection('OLD', evidence)} IS NOT {projection('NEW', evidence)})")
        for operation, condition in (
            ('INSERT', "NEW.tab IN ('Job History','Job Evidence')"),
            ('DELETE', "OLD.tab IN ('Job History','Job Evidence')"),
            ('UPDATE', "(OLD.tab IN ('Job History','Job Evidence') OR NEW.tab IN ('Job History','Job Evidence')) AND (" + changed + ')'),
        ):
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS review_queue_{operation.lower()}
                AFTER {operation} ON records WHEN {condition} BEGIN
                UPDATE review_input_revisions SET queue=queue+1 WHERE id=1; END''')
        # Control reconciliation depends on current records, merge baselines,
        # delivery intents and schema/profile metadata. Conservative invalidation
        # is cheap and never suppresses the mandatory live remote read.
        for table in ('records', 'baseline', 'delivery_attempts', 'tabs'):
            for operation in ('INSERT', 'UPDATE', 'DELETE'):
                prefixes = ('OLD', 'NEW') if operation == 'UPDATE' else (('NEW',) if operation == 'INSERT' else ('OLD',))
                condition = ' OR '.join(f"{p}.tab='Job History'" for p in prefixes)
                db.execute(f'''CREATE TRIGGER IF NOT EXISTS review_controls_{table}_{operation.lower()}
                    AFTER {operation} ON {table} WHEN {condition} BEGIN
                    UPDATE review_input_revisions SET controls=controls+1 WHERE id=1; END''')
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise


def revision(repo, kind):
    if kind not in ('queue', 'controls'):
        raise ValueError('Unknown review revision')
    if not getattr(repo, 'is_local', False):
        return None
    if not repo.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='review_input_revisions'").fetchone():
        return None  # Older/read-only databases are never treated as reusable.
    row = repo.db.execute(f'SELECT epoch,{kind} FROM review_input_revisions WHERE id=1').fetchone()
    return list(row) if row else None
