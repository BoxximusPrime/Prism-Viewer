# Prism login artwork

The approved emerald crystal concept supplies the background and icon. The
background is artwork only; all branding, text, account selection and buttons
are native viewer controls.

`prism-login-background-source.png` was extracted with the built-in image
generator using this prompt:

> Edit target: the supplied approved Prism login mockup. Produce ONLY its background artwork, a clean production background plate with ABSOLUTELY NO UI OR BRANDING. Remove the small green logo and PRISM wordmark at top left. Remove the entire login card on the right, all form elements, ALL TEXT, all buttons, all links, and all footer/status dots/text. Seamlessly inpaint the areas they occupied with the surrounding dark photographic background. Preserve the large clear faceted crystal in the left interior, white incident beam fading in from left, realistic rainbow refraction and reflective dark floor, precise existing crystal silhouette, lighting and scale. Keep the right third quiet and very dark to support live UI drawn separately. Preserve the broad seamless fades into solid charcoal #101416 at both left and right edges. The far edges must be the same solid color top to bottom; no bright ray touching a boundary. Wide 16:9 high resolution background image. Do not include a checkerboard. This background is opaque. No new objects, no inscriptions, no watermark. Preserve the approved composition as closely as possible.

Regenerate the skin textures with `python scripts/prepare_prism_login_art.py`.
This uses Pillow to normalize the background to 1920×1080, smoothly finish all
edges at #101416, and prepare the logo and rounded surface. The login card uses
live GPU backdrop blur, followed by a translucent charcoal surface.

Any native `panel` can opt in with `backdrop_blur="20"` (Gaussian sigma in UI
pixels, clamped to 0–64) and `backdrop_corner_radius="6"`. Zero blur is the
default and has no capture cost. Existing background colors/images provide
the tint; they and child controls are drawn after the blur. Match the corner
radius to the panel's surface artwork. The renderer captures earlier content
in draw order at quarter resolution, with padded edges and two Gaussian
passes. Visible glass panels bypass the optional UI framebuffer cache so
world motion and overlapping panels stay current. If shaders are unavailable,
the ordinary panel tint still draws. Buffers are released with GL resources.

Run `.venv/Scripts/python.exe scripts/tests/test_ui_backdrop_gpu.py` for GPU
checks of filtering, source updates, coordinates, rounded corners and opacity.

`prism-emerald-mark-v1.png` is the transparent icon master, extracted from the
same concept with the image generator and cleaned with an antialiased local
silhouette mask. Regenerate platform icons with:

`python scripts/generate_boxxy_branding.py artwork/prism/prism-emerald-mark-v1.png --icons-only`

The login texture preparation also copies this mark into the skin at 256×256.
It generates the login button's emerald faceted normal, hover and pressed
textures from simple geometry. The native button still draws its own label,
focus indication and disabled state. Change `connect_btn` in `panel_login.xml`
to tune its images or colors; no C++ rebuild is needed for skin changes.

The world-loading view reuses the same crystal drawing in `LLPanelLogin` and
the same rounded surface texture. Its pane, tint, solid green progress bar,
percentage, and message area are in `panel_progress.xml`. `pulse="false"` keeps
the green fill steady; the bar still uses real startup progress. Long server
messages scroll within the centered pane. The login menu's **Debug > UI Tests >
Loading Screen** opens an animated local preview; **Back** or **Escape** closes
it without connecting to a grid. The crystal stays through the login fade,
while teleport progress leaves the live world visible behind the same frosted
pane and solid green bar. Other progress screens retain their existing background.
During teleporting, the progress view sits below floaters so conversation windows
remain usable without losing keyboard focus. It still blocks clicks into the world,
and the existing progress-visible check continues to block movement controls.
Run `.venv/Scripts/python.exe scripts/tests/test_teleport_progress_ui.py` to check
the XUI layers and production focus/routing methods without connecting to a grid.
These assets and the login implementation are in progress until committed;
platform verification is recorded in FEATURES.md.
