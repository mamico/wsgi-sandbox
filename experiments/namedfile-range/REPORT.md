# Range requests on `@@download` with six WSGI servers

Compares plone.namedfile `main` ([`2010c04`][main-commit]) with [PR #226][pr] ([`6fd9c5d`][pr-commit], "Stop
`filestream_range_iterator.read` at the end of the range") on a real Plone site, with waitress, bjoern,
pyruvate, gunicorn, uWSGI and cheroot.

[main-commit]: https://github.com/plone/plone.namedfile/commit/2010c047e53ce3f74a96e21692e4ea4d7a169ede
[pr]: https://github.com/plone/plone.namedfile/pull/226
[pr-commit]: https://github.com/plone/plone.namedfile/pull/226/commits/6fd9c5d3fb4b3bf089ed4e4e2458f52cb6b4b5d2

## Summary

- PR #226 fixes range requests with an end on every server that reads the iterator through `wsgi.file_wrapper` (all except cheroot): the iterator produces only the range.
- Before the PR, bjoern and uWSGI sent the rest of the file after `Content-Length` and broke the next request on a keep-alive connection. waitress, pyruvate and gunicorn cut at `Content-Length`, so the client was fine, but they read the rest of the file (pyruvate into memory). cheroot was already correct: it does not use `wsgi.file_wrapper`.
- Open ranges (`bytes=N-`, `bytes=-N`) were already correct everywhere.
- Not covered by the PR: a full download (no Range, or `bytes=0-`) on bjoern and pyruvate reads the whole file in one `read()` (+127 MiB RSS for 64 MiB).
- A `fileno()` that is only available for whole-file responses lets bjoern, pyruvate, gunicorn and uWSGI use `sendfile` and is correct on all six servers. A `fileno()` that is always available breaks ranges on bjoern, pyruvate and uWSGI (see the last section).
- uWSGI 2.0.31 has a bug of its own: the block size of `wsgi.file_wrapper` is an uninitialized variable when the app does not pass one, and Zope does not.

## Setup

Variants: `main` ([`2010c04`][main-commit]), `pr` ([`6fd9c5d`][pr-commit]), and two patched variants in the last section, `pr-fileno` and `pr-fileno-whole`. The sections up to the last one compare `main` and `pr` only. `pr-fileno-whole` was run on all servers except waitress, which ignores `fileno()`.

- Plone 6.2.2, Zope 6.2, Python 3.12.9, plone.namedfile 8.1.2.dev0 (all variants, only the PR commit and the patches differ).
- waitress 3.0.2 (4 threads), bjoern 3.2.2, pyruvate 1.6.1 (2 workers, `max_reuse_count=100`), gunicorn 26.2.0 (one `gthread` worker, 4 threads), uWSGI 2.0.31 (`--http11-socket`, one process, 4 threads), cheroot 11.1.2 (4 threads).
- gunicorn: the Plone 6.2 constraints pin 26.2.2, which is not on PyPI, so the sandbox installs 26.2.0.
- One File of 64 MiB (deterministic bytes) in a committed blob, served from `/plone/big-file/@@download/file`.
- Raw socket client, HTTP/1.1 with `Connection: keep-alive`. It checks status, headers and every byte of the body, then counts bytes the server sends after `Content-Length`.
- Server side: bytes and largest chunk the range iterator returned, and peak RSS of the server process tree (VmHWM).
- Full tables: `results/tables.md`, raw data: `results/results.json` (regenerate with `make run`).

## Why the server matters

Zope hands the range iterator to `wsgi.file_wrapper` when the server offers one, because the iterator has a `read` method. The iterator has no `fileno()`, so no server uses `sendfile`. Each server then reads the iterator in its own way:

| server | how it reads the iterator | cuts the body at Content-Length |
|---|---|---|
| waitress | `read(32768)` in a loop | yes |
| bjoern | `read()` with no argument, one chunk | no |
| pyruvate | `read(-1)`, one chunk | yes |
| gunicorn | `read(8192)` in a loop | yes |
| uWSGI | `read(n)` in a loop, `n` uninitialized (about 30 KiB in these runs); one `read()` if `n` ≤ 0 | no |
| cheroot | no `wsgi.file_wrapper`: Zope returns the iterator, cheroot iterates it (`__next__`, 64 KiB blocks) | not needed, `__next__` stops at the end of the range |

Before the PR `read()` ran to the end of the file, not to the end of the range. `__next__` already stopped at the end of the range.

## Results, range requests

Bytes the iterator produced, for a request that needs 1 KiB (`bytes=0-1023`) and for 1 MiB in the middle of the file (`bytes=32MiB-33MiB`):

| server | variant | `bytes=0-1023` | extra bytes sent to client | peak RSS + | 1 MiB in the middle | next request on the connection |
|---|---|---|---|---|---|---|
| waitress | main | 64.0 MiB | 0 | 88 KiB | 32.0 MiB | ok |
| waitress | pr | 1 KiB | 0 | 16 KiB | 1.0 MiB | ok |
| bjoern | main | 64.0 MiB | 67,107,840 | 127.3 MiB | 32.0 MiB (32,505,856 extra) | **broken** |
| bjoern | pr | 1 KiB | 0 | 0 | 1.0 MiB | ok |
| pyruvate | main | 64.0 MiB | 0 | 63.2 MiB | 32.0 MiB | closed |
| pyruvate | pr | 1 KiB | 0 | 8 KiB | 1.0 MiB | closed |
| gunicorn | main | 64.0 MiB | 0 | 0 | 32.0 MiB | ok |
| gunicorn | pr | 1 KiB | 0 | 0 | 1.0 MiB | ok |
| uWSGI | main | 64.0 MiB | 67,107,840 | 60 KiB | 32.0 MiB (32,505,856 extra) | **broken** |
| uWSGI | pr | 1 KiB | 0 | 8 KiB | 1.0 MiB | ok |
| cheroot | main | 1 KiB | 0 | 20 KiB | 1.0 MiB | ok |
| cheroot | pr | 1 KiB | 0 | 16 KiB | 1.0 MiB | ok |

In all 84 runs (6 servers x 2 variants x 7 scenarios) the first response carried the correct status, `Content-Range` and body bytes. The difference is in what the server did and sent besides that.

- **waitress** and **gunicorn**: the client is fine either way, both cut at `Content-Length`. Before the PR they still read the file from the start of the range to the end, 64 MiB for a 1 KiB range, in small blocks. With the PR they read the range.
- **bjoern** and **uWSGI**: before the PR the response is broken at protocol level. They do not cut at `Content-Length`, so they send the rest of the file after the 1 KiB body: 67,107,840 extra bytes. On a keep-alive connection the next request got those bytes as its response (`ValueError: not a status line`). bjoern also holds the rest of the file in memory as one chunk (+127 MiB RSS for a 64 MiB file); uWSGI reads it in blocks. With the PR: no extra bytes, the second request on the same connection works.
- **pyruvate**: the client is fine, pyruvate cuts at `Content-Length`. Before the PR the rest of the file is read into memory as one chunk (+63.2 MiB RSS for a 1 KiB range). With the PR memory follows the range size.
- **cheroot**: same results before and after, because it never calls `read()`.
- Ranges that end at the end of the file (`open-ended`, `suffix`) are identical before and after. Zope's `expandRanges` sets `end` to the file size, so the end of the range is the end of the file, where `read()` stopped before the PR too.

## Observations outside the PR

- **Full download (no Range, or `bytes=0-`) on bjoern and pyruvate** reads the whole file in one `read()` call: largest chunk 64.0 MiB and peak RSS +127 MiB, about twice the file size. The PR does not change this. A 1 GiB download would need about 2 GiB of RAM on those two servers. The other servers read in blocks: waitress 32 KiB (peak +11 to 25 MiB across runs), gunicorn 8 KiB, uWSGI about 30 KiB, cheroot 64 KiB (peak below 1 MiB for the last three).
- **uWSGI block size**: `py_uwsgi_sendfile` in `plugins/python/wsgi_handlers.c` declares `int chunk_size;` without a value and parses the optional block size with `PyArg_ParseTuple(args, "O|i", ...)`. Zope calls `wsgi.file_wrapper(body)` without a block size, so uWSGI uses whatever is on the stack: blocks of 30,295, 31,568 and 32,323 bytes in these runs. If the value is 0 or negative, uWSGI calls `read()` once and holds the whole file in memory, like bjoern and pyruvate. The code is the same on uWSGI `master`. Zope could avoid it by passing a block size, which PEP 3333 allows.
- **waitress rchar**: for a full 64 MiB download the process reads 2 to 3 GB (varies per run). Waitress reads its own overflow buffer file back while sending. Not related to the PR, but it makes `/proc` read counters useless here, hence the iterator counters.
- **pyruvate keep-alive**: with 1.6.1 the connection is closed after every response, also with `max_reuse_count=100`, also for a request Zope never sees (`/__sandbox_stats`), and also seen with curl (no connection reuse). The log shows `Could not handle read event: ... "Incomplete request"`. The "next request" check is therefore not meaningful for pyruvate, the table shows `closed`.
- `Content-Length` truncation by waitress, pyruvate and gunicorn hides the problem from clients, so only server-side counters showed it. bjoern and uWSGI are the servers where a client can see it.

## Limits

- Loopback, one client, sequential requests. Memory numbers are peak RSS of the server process tree, not a load test.
- Only `@@download` was tested, not `@@display-file` (same iterator) or images.
- Servers ran with defaults apart from the options listed above. uWSGI was tested with its own HTTP socket, not behind nginx with the uwsgi protocol. A proxy in front can change what the client sees (for example the bytes after `Content-Length`), but not what the server reads.

## Follow-up: `fileno()` on the iterator

Idea: if the iterator has `fileno()`, the servers that support it use `sendfile` and never load the file. Two variants on top of the PR, as patches in `patches/` (nothing is changed in the plone.namedfile repo):

- `pr-fileno`: `fileno()` always returns the file descriptor.
- `pr-fileno-whole`: `fileno()` returns it only when the response is the whole file: `start == 0` and `end` is `None` (no Range) or the file size (`bytes=0-`, because `expandRanges` sets `end` to the size). Otherwise it raises `OSError`, so the server falls back to `read()`.

Whole file of 64 MiB, peak RSS above the idle server:

| server | request | PR | `pr-fileno` | `pr-fileno-whole` |
|---|---|---|---|---|
| bjoern | no Range | +127.6 MiB | 0 | 0 |
| bjoern | `bytes=0-` | +127.6 MiB | 0 | 0 |
| pyruvate | no Range | +127.0 MiB | 0 | 0 |
| pyruvate | `bytes=0-` | +126.9 MiB | 0 | 0 |

gunicorn and uWSGI already read the whole file in blocks with the PR (peak below 1 MiB). With either `fileno()` variant they use `sendfile` for a whole file: the iterator returns 0 bytes. waitress and cheroot do not use `fileno()`.

Range requests with `pr-fileno` (always `fileno()`):

- **bjoern** sends from the right offset but does not stop at the end of the range: the 67,107,840 extra bytes and the broken keep-alive request of the original bug are back (same as `main`).
- **pyruvate** starts `sendfile` at offset 0, not at the position of the descriptor. `bytes=0-1023` is correct by luck; `middle-1m`, `open-ended` and `suffix` return **wrong bytes** (`body_ok` False). This is data corruption, not only inefficiency.
- **uWSGI** sends the whole file from offset 0 (`uwsgi_response_sendfile_do(wsgi_req, fd, 0, 0)`): wrong bytes for `middle-1m`, `open-ended` and `suffix`, and the rest of the file after `Content-Length` for every range, so the next request on the connection breaks.
- **gunicorn** is correct: it starts `sendfile` at the position of the descriptor and sends `Content-Length` bytes.
- waitress and cheroot ignore `fileno()`, results are the same as the PR.

With `pr-fileno-whole` all 7 scenarios are correct on bjoern, pyruvate, gunicorn, uWSGI and cheroot: whole-file downloads (no Range and `bytes=0-`) use `sendfile` where the server supports it, with no memory cost, and ranges use the iterator like the PR (no extra bytes, memory follows the range size).

Caveats: tested only on these server versions and with a committed blob on local disk. `fileno()` makes the file descriptor visible to anything that checks for it, not only WSGI servers. Whether this belongs in plone.namedfile is a separate decision from PR #226.
