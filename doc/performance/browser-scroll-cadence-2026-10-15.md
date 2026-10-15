# Embedded browser scroll cadence — 2026-10-15

Status: implemented and verified in Release, uncommitted. The reported symptom is
choppy scrolling in ordinary pages inside the browser floater, even when the page
reports high FPS. The patch improves helper pixel delivery; the exact reported
5–10 FPS presentation case was not reproduced.

## Findings and implementation

The existing CEF plugin already requests 120 FPS. Normal media priority serviced
SLPlugin every 20 ms, high priority every 10 ms, and the child clamped shorter
requests to 10 ms. On this Windows machine, these waits grouped notifications
into approximately 31.2 ms and 15.6 ms intervals. Chromium's animation and paint
message counts stayed near 120/s while many notifications referred to the same
latest shared-memory image.

The patch sets normal/high media servicing to 1/120 s and permits that interval
in the child. SLPlugin requests a 1 ms Windows timer resolution while servicing
foreground media, releases it at lower priorities, and balances it before plugin
destruction. The viewer's own timer request does not cover the separate process
on current Windows: see [Microsoft's timer documentation](https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod).
Low-priority and hidden/slideshow intervals remain 40 ms and 1 s.

The user's saved `RenderGLMultiThreadedMedia` is enabled. Added capture scopes
distinguish main-thread submission, worker completion, and synchronous uploads.
These scopes count viewer frames with activity across all media, not individual
presented images. The first repeated live captures, at approximately 26 viewer
FPS, found submissions and completions on every viewer frame, so the upload
scheduling was left unchanged. The later 120 FPS scene exposes a remaining
approximately 89 updates/s limit, detailed below.

## Isolated pixel-delivery measurements

`scripts/tests/browser_plugin_cadence.py` launches the shipped Release SLPlugin
with a fresh cache under `.logs/browser-cadence/`, a loopback protocol socket,
and a 960 × 640 shared-memory image. It loads the local
`scripts/tests/browser_scroll.html?auto` fixture. Each animation callback changes
a fixed corner pixel to encode a frame number and scrolls a long text page.
The harness records arrival times, decoded pixel frame numbers, console callback
rates, and the helper's existing CPU heartbeat. It uses no user browser session.

Each interval warms for 3 seconds, then measures 8 seconds. The baseline has two
repeats; the timer patch has three, reversing interval order on alternate repeats.
Baseline ran alongside the logged-in viewer; the patched helper ran while the
viewer was closed and the Release build was completing. This load difference is
a comparison limitation. The timer-aligned delivery intervals, unchanged callback
rate, and within-process interval sweep support the pacing diagnosis, but these
numbers are not in-viewer presentation FPS.

| Helper | Requested interval | Distinct received pixel frames/s, mean |
| --- | ---: | ---: |
| Baseline | 20 ms (normal) | 32.05 |
| Baseline | 10 ms (high) | 63.61 |
| Baseline | 1 ms (clamped to 10 ms) | 63.66 |
| Precise timer | 20 ms | 49.76 |
| Precise timer | 10 ms | 84.75 |
| Precise timer | 8.333 ms (new foreground) | 89.56 |

All runs reported approximately 120 page callbacks and paint notifications per
second. New foreground median delivery intervals were 9.08–9.16 ms, with p95
18.08–18.50 ms. Normal baseline median was about 31.2 ms and p95 about 33 ms.
The helper heartbeat fraction was approximately 0.12–0.13 across these cases;
that counter excludes Chromium subprocesses and is not total CPU utilization.

Raw artifacts include exact binary SHA-256 identities and every sampled frame:

- [Baseline](../../.logs/browser-cadence/baseline-0f00859d/results.json)
- [Precise timer](../../.logs/browser-cadence/precise-timer-0356f481/results.json)
- [Background/resume transitions](../../.logs/browser-cadence/background-transition-0b256756/results.json): two alternating repeats, 3 s warmup and 4 s samples. Foreground delivered 89.7–90.7 distinct frames/s, low priority 21.3–21.4, and hidden 0.99–1.00. Resuming foreground restored the higher rate.

## Viewer setup and verification

Canonical executable: `build-vc170-64/newview/Release/secondlife-bin.exe`.
Build command: `cmake --build build-vc170-64 --config Release --target secondlife-bin -- /m:2`.
No class layouts changed. The initial sandboxed build could not start normally;
it was stopped and the same Release command was run outside the sandbox.

Original scene: ACCESS, 1008 × 699 viewer viewport (1008 × 646 render area), NVIDIA
RTX 5090, driver 617.14. The saved camera was restored after restart and the window
was returned to these dimensions. No graphics overrides were applied for these
browser tests. Restarting the viewer restored persisted settings, which differ
from the initial session's overrides: notably VSync and hair physics were enabled
after restart. Existing unrelated workspace changes were also included in the
Release build. The initial and rebuilt viewer FPS therefore cannot be compared
as an isolated browser optimization measurement.
[Original camera](../../.logs/viewer-mcp/20261015T115124Z-browser-scroll-original-32e28af0.camera.json).

An initial 120-warmup/360-sample MCP capture with the ordinary browser open had
19.33 ms median viewer interval (about 51.7 FPS). It predates the media scopes and
was taken before starting the scroll fixture, so it cannot establish browser FPS.
[Initial capture](../../.logs/viewer-mcp/20261015T114950Z-profile-2fd53122.json).
Baseline viewer SHA-256: `cd447f5f8d38709dfa5bc6fa13153e70be13a9ce151900852b6653afe42c898b`.

The Release build completed successfully. Rebuilt viewer SHA-256:
`2db8a5b215f2cc401fd5cb220ee556bf86db8891521b7c66f4db04dff87c92c4`.
Production priority/timer transition regression, protocol serialization checks,
Python compilation, and the existing MCP CPU capture regression passed.

## Repeated live upload captures

The local scrolling fixture was displayed in a 920 × 614 browser floater with a
912 × 512 content area. The viewer remained foreground, with the restored camera
locked, at the same viewport throughout. Each of three runs warmed for 240 viewer
frames and sampled 600. The page reported 120 animation callbacks/s.

Settings were unchanged across these runs: deferred rendering on, resolution
divisor 1, FSAA 2, shadow detail 2, VSync on, multithreaded media on. Full settings,
camera, scene and raw timing samples are recorded in the linked artifacts.

| Run | Median viewer interval | Mean viewer FPS | Frames submitting / completing media uploads |
| --- | ---: | ---: | ---: |
| [1](../../.logs/viewer-mcp/20261015T121042Z-profile-46a79f7f.json) | 38.45 ms | 25.56 | 600 / 600 |
| [2](../../.logs/viewer-mcp/20261015T121154Z-profile-b8b957c2.json) | 37.49 ms | 26.40 | 600 / 600 |
| [3](../../.logs/viewer-mcp/20261015T121243Z-profile-670c771b.json) | 37.63 ms | 26.22 | 600 / 600 |

[Matching visual check](../../.logs/viewer-mcp/20261015T121053Z-browser-scroll-patched-threaded-dec30988.png)
shows the scrolling page, readable text and borders, and its callback counter.
No blank or corrupt browser surface was observed. A still screenshot does not
establish motion smoothness.

These runs show the media worker keeping up with the viewer. They do not count
distinct screen-presented page images, and the scopes aggregate all media.
Visible browser updates cannot exceed the viewer frame rate. The helper test
separately demonstrates why 120 page callbacks/s did not mean 120 distinct images
delivered to the viewer. Faster delivery is verified; eliminating the user's exact
5–10 FPS symptom still needs confirmation in the affected page and scene.

Manual mouse-wheel scrolling also moved the paused fixture correctly. After the
captures, automatic scrolling was stopped, the browser returned to its previous
page, and the camera lock was released. The original viewport was retained.

## Follow-up in the user's 120 FPS scene

The user moved to Brianconnais and requested another measurement. The running
Release executable has the same SHA-256 recorded above; no rebuild or production
code changes were made for this session. Viewport: 3440 × 1369, render area:
3440 × 1316, same RTX 5090 and driver. Camera position was
`[289289.3936100006, 278764.0472564697, 1448.002685546875]`, forward vector
`[0.8228256106376648, 0.5431854724884033, -0.16705554723739624]`, vertical FOV
60 degrees. The camera remained unlocked and unchanged across capture start/end
metadata and all three runs. No camera or graphics overrides were applied.

A passive capture of the mostly static Destination Guide warmed for 240 frames
and sampled 1200: 119.93 viewer FPS, four frames with media upload completions.
Static content does not establish sustained browser cadence.
[Passive capture](../../.logs/viewer-mcp/20261015T122454Z-profile-907f4b74.json),
[initial visual state](../../.logs/viewer-mcp/20261015T122422Z-browser-high-fps-current-c0c0c0f3.png).

For sustained activity, a separate browser displayed the same local automatic
scroll fixture at 920 × 614, with a 912 × 512 content area. Destination Guide
remained open behind it. Each of three runs warmed for 360 frames and sampled
1200 (approximately 3 seconds warmup and 10 seconds recording). The test page
reported 120 animation callbacks/s. The viewer was foreground at both ends of
every capture. Settings were identical across all runs and capture start/end:
`MaxFPS=120`, VSync on, multithreaded media on, deferred rendering on, resolution
divisor 1, FSAA 2 and shadow detail 2. Full settings are in the raw JSON files.

| Run | Viewer FPS | Frames with upload submissions / completions | Completion-active frames/s | Median / p95 interval between completion-active frames |
| --- | ---: | ---: | ---: | ---: |
| [1](../../.logs/viewer-mcp/20261015T122954Z-profile-05e3c999.json) | 119.98 | 902 / 902 | 90.19 | 8.94 / 17.77 ms |
| [2](../../.logs/viewer-mcp/20261015T123022Z-profile-9f83c59c.json) | 120.00 | 885 / 885 | 88.50 | 8.50 / 17.43 ms |
| [3](../../.logs/viewer-mcp/20261015T123050Z-profile-9af9328e.json) | 119.90 | 893 / 893 | 89.23 | 8.57 / 17.44 ms |

Across all runs, 2680 of 3600 viewer frames contained a media upload completion:
89.3 completion-active frames/s over approximately 30 seconds. Of 2677 measured
gaps, 1808 spanned one viewer frame, 818 spanned two, and 51 spanned three. Thus
32.5% of gaps span two or three viewer frames; the longest measured gap was
27.46 ms. This uneven update spacing is consistent with the remaining perceived
roughness despite a 120 FPS world.

Rates use sample count divided by the sum of `frame_interval_ms`; gap estimates
use cumulative viewer frame intervals between samples containing
`media.texture_present`. Presence of the scope, including very short scopes
whose overhead-adjusted duration is negative, determines activity. These are
frames where the viewer receives completed textures, not direct display-scanout
or distinct-pixel counts. Scopes aggregate all media, and the mostly static
Destination Guide may contribute occasional updates. The scrolling test browser
is smaller than the user's original Destination Guide window, so these results
do not establish performance at its original size or on every ordinary page.

[Matching visual check](../../.logs/viewer-mcp/20261015T123051Z-browser-high-fps-scrolling-f137a67e.png)
shows the scrolling fixture, 120 page callbacks/s, intact text and borders, and
the world FPS counter. A still screenshot cannot establish motion smoothness.

The approximately 89 updates/s result closely matches the isolated helper's
89.56 distinct pixel frames/s. This supports investigating helper frame pacing
and delivery next; it does not isolate every possible upload or presentation
delay. The world renderer is no longer the approximately 26 FPS ceiling in this
scene. Reaching consistently spaced 120 browser updates/s remains unfinished.

The temporary test browser was closed afterward and Destination Guide remained
on its original page. Activating the native window during setup temporarily
restored it from maximized, which clamped Destination Guide to a smaller size;
the viewer was maximized again before all three scrolling captures. Its viewport
was restored, but the Destination Guide floater remained smaller. Camera and
graphics settings were unchanged.
