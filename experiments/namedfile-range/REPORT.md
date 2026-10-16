# Range requests on `@@download` with waitress, bjoern and pyruvate

Compares plone.namedfile `main` (`2010c04`) with PR #226 (`6fd9c5d`, "Stop
`filestream_range_iterator.read` at the end of the range") on a real Plone site.

## Summary

- PR #226 fixes range requests with an end on all three servers: the iterator produces only the range (waitress and pyruvate no longer read or buffer the rest of the file, bjoern no longer sends bytes after `Content-Length`).
- Open ranges (`bytes=N-`, `bytes=-N`) were already correct.
- Not covered by the PR: a full download (no Range, or `bytes=0-`) on bjoern and pyruvate reads the whole file in one `read()` (+127 MiB RSS for 64 MiB). A `fileno()` that is only available for whole-file requests removes that cost without breaking ranges; a `fileno()` that is always available breaks them (see the last section).

## Setup

Variants: `main` (`2010c04`), `pr` (`6fd9c5d`), and two patched variants in the last section, `pr-fileno` and `pr-fileno-whole`. The sections up to the last one compare `main` and `pr` only. `pr-fileno-whole` was run on bjoern and pyruvate only, waitress ignores `fileno()`.

- Plone 6.2.2, Zope 6.2, Python 3.12.9, plone.namedfile 8.1.2.dev0 (both variants, only the PR commit differs).
- waitress 3.0.2 (4 threads), bjoern 3.2.2, pyruvate 1.6.1 (2 workers, `max_reuse_count=100`).
- One File of 64 MiB (deterministic bytes) in a committed blob, served from `/plone/big-file/@@download/file`.
- Raw socket client, HTTP/1.1 with `Connection: keep-alive`. It checks status, headers and every byte of the body, then counts bytes the server sends after `Content-Length`.
- Server side: bytes and largest chunk the range iterator returned, and peak RSS of the server (VmHWM).
- Full tables: `results/tables.md`, raw data: `results/results.json` (regenerate with `make run`).

## Why the server matters

Zope hands the range iterator to `wsgi.file_wrapper` because it has a `read` method. The iterator has no `fileno()`, so no server uses `sendfile`. Each server then reads the iterator in its own way:

| server | how it reads the wrapped iterator | cuts the body at Content-Length |
|---|---|---|
| waitress | `read(32768)` in a loop | yes |
| bjoern | `read()` with no argument, one chunk | no |
| pyruvate | `read(-1)`, one chunk | yes |

Before the PR `read()` ran to the end of the file, not to the end of the range.

## Results, range requests

Bytes the iterator produced, for a request that needs 1 KiB (`bytes=0-1023`) and for 1 MiB in the middle of the file (`bytes=32MiB-33MiB`):

| server | variant | `bytes=0-1023` | extra bytes sent to client | peak RSS + | 1 MiB in the middle |
|---|---|---|---|---|---|
| waitress | main | 64.0 MiB | 0 | 88 KiB | 32.0 MiB |
| waitress | pr | 1 KiB | 0 | 16 KiB | 1.0 MiB |
| bjoern | main | 64.0 MiB | 67,107,840 | 126.9 MiB | 32.0 MiB (32,505,856 extra) |
| bjoern | pr | 1 KiB | 0 | 0 | 1.0 MiB |
| pyruvate | main | 64.0 MiB | 0 | 62.6 MiB | 32.0 MiB |
| pyruvate | pr | 1 KiB | 0 | 8 KiB | 1.0 MiB |

All 42 responses (3 servers x 2 variants x 7 scenarios) carried the correct status, `Content-Range` and body bytes. The difference is in what the server did and sent besides that.

- **waitress**: the client is fine either way, waitress cuts at `Content-Length`. Before the PR it still read the file from the start of the range to the end, 64 MiB for a 1 KiB range. With the PR it reads the range.
- **bjoern**: before the PR the response is broken at protocol level. bjoern does not cut at `Content-Length`, so it sends the rest of the file after the 1 KiB body: 67,107,840 extra bytes. On a keep-alive connection the next request got those bytes as its response (`ValueError: not a status line`). The whole rest of the file is also in memory as one chunk (+127 MiB RSS for a 64 MiB file). With the PR: no extra bytes, the second request on the same connection works.
- **pyruvate**: the client is fine, pyruvate cuts at `Content-Length`. Before the PR the rest of the file is read into memory as one chunk (+62.6 MiB RSS for a 1 KiB range). With the PR memory follows the range size.
- Ranges that end at the end of the file (`open-ended`, `suffix`) are identical before and after. Zope's `expandRanges` sets `end` to the file size, so the end of the range is the end of the file, where `read()` stopped before the PR too.

## Observations outside the PR

- **Full download (no Range, or `bytes=0-`) on bjoern and pyruvate** reads the whole file in one `read()` call: largest chunk 64.0 MiB and peak RSS +127 MiB, about twice the file size. waitress reads 32 KiB blocks, peak +11 to 25 MiB. The PR does not change this. A 1 GiB download would need about 2 GiB of RAM on those two servers.
- **waitress rchar**: for a full 64 MiB download the process reads 2 to 3 GB (varies per run). Waitress reads its own overflow buffer file back while sending. Not related to the PR, but it makes `/proc` read counters useless here, hence the iterator counters.
- **pyruvate keep-alive**: with 1.6.1 the connection is closed after every response, also with `max_reuse_count=100`, also for a request Zope never sees (`/__sandbox_stats`), and also seen with curl (no connection reuse). The log shows `Could not handle read event: ... "Incomplete request"`. The "next request" check is therefore not meaningful for pyruvate, the table shows `closed`.
- `Content-Length` truncation by pyruvate and waitress hides the problem from clients, so only server-side counters showed it. bjoern is the only one of the three where a client can see it.

## Limits

- Loopback, one client, sequential requests. Memory numbers are peak RSS of the server process tree, not a load test.
- Only `@@download` was tested, not `@@display-file` (same iterator) or images.
- Servers ran with defaults apart from the worker counts listed above. gunicorn and uWSGI were not tested.

## Follow-up: `fileno()` on the iterator

Idea: if the iterator has `fileno()`, bjoern and pyruvate use `sendfile` and never load the file. Two variants on top of the PR, as patches in `patches/` (nothing is changed in the plone.namedfile repo):

- `pr-fileno`: `fileno()` always returns the file descriptor.
- `pr-fileno-whole`: `fileno()` returns it only when the response is the whole file: `start == 0` and `end` is `None` (no Range) or the file size (`bytes=0-`, because `expandRanges` sets `end` to the size). Otherwise it raises `OSError`, so the server falls back to `read()`.

Whole file of 64 MiB, peak RSS above the idle server:

| server | request | PR | `pr-fileno` | `pr-fileno-whole` |
|---|---|---|---|---|
| bjoern | no Range | +127.6 MiB | 0 | 0 |
| bjoern | `bytes=0-` | +127.6 MiB | 0 | 0 |
| pyruvate | no Range | +127.0 MiB | 0 | 0 |
| pyruvate | `bytes=0-` | +126.9 MiB | 0 | 0 |

Range requests with `pr-fileno` (always `fileno()`):

- **bjoern** sends from the right offset but does not stop at the end of the range: the 67,107,840 extra bytes and the broken keep-alive request of the original bug are back (same as `main`).
- **pyruvate** starts `sendfile` at offset 0, not at the position of the descriptor. `bytes=0-1023` is correct by luck; `middle-1m`, `open-ended` and `suffix` return **wrong bytes** (`body_ok` False). This is data corruption, not only inefficiency.
- waitress ignores `fileno()`, results are the same as the PR.

With `pr-fileno-whole` all 7 scenarios are correct on bjoern and pyruvate: whole-file downloads (no Range and `bytes=0-`) use `sendfile` with no memory cost, ranges use the iterator like the PR (no extra bytes, memory follows the range size).

Caveats: tested only on these server versions and with a committed blob on local disk. `fileno()` makes the file descriptor visible to anything that checks for it, not only WSGI servers. Whether this belongs in plone.namedfile is a separate decision from PR #226.
