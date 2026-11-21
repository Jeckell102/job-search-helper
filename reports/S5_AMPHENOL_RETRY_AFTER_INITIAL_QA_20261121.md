# AcquireTM Retry-After failure evidence

The installed adapter `a95953af…` and the fresh generated adapter share
the same eight-second retry cap. The new regression fixture was run
against the installed adapter bytes. Its three long-header subcases each
observed three requests instead of one. The cases used numeric HTTP 429,
absolute-date HTTP 429 and absolute-date HTTP 503. No real provider or
browser was used.

Root's first private correction `d8268569…` stopped each detail call and
carried the exact UTC deadline in its result. Independent QA then ran the
actual ordinary whole-Company retry function with a disposable worker.
The staged 429 returned `blocked` and stopped. The staged 503 returned
`partial`, which led the outer worker to make a second Company attempt
before the deadline. This rejected a generalized cooldown claim.

The corrected version routes an explicit wait beyond the inline budget to
the existing `blocked` hold for all those statuses. Existing short retry
and final short 5xx classification remain unchanged. The workflow must not
use the human-readable deadline to claim automatic deadline scheduling.
The generated pagination wrapper and its actual release proposal remain
separately pinned. No production or release change was made here.
