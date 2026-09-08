# Prism Feature Inventory

This document tracks major features and user-facing customizations added to Prism beyond the official Second Life viewer.

The committed feature list is based on the differences from the `upstream/develop` branch, the Prism commit history, and related development notes. Current uncommitted changes may include additional work in progress and should not be treated as final until committed.

## Prism-specific systems

- Nameplate chat-range colors can be enabled or disabled in Prism preferences and update immediately. (in progress; runtime verification pending)

- First-run defaults: translation and sending look targets off, gesture sounds on, all available toolbar buttons present, 540×480 DM floaters, and green/brown name-tag chat ranges. Window title is `Prism`, then `Prism - <account name>` after login. Privacy labels use “Send My Look Targets” and “Show Look Targets”. (in progress; updated installer testing pending)

- Redesigned login with the neutral crystal-to-wireframe Prism logo, an emerald/charcoal backdrop and a compact rounded login card in its established position, flat fields and full-width focus outlines. (in progress; verified in Release at ultrawide and windowed sizes)

- Prism product branding, separate Prism settings/cache directories and Windows installer identity; uninstall preserves preferences. Existing Boxxy AO inventory folders and saved setting keys remain compatible. (in progress; Windows Release installer built for initial testing, install/uninstall verification pending)

- Bundled UI sounds for opening floaters, buttons, floater focus changes, and checkboxes, using the existing UI audio controls. (in progress)
- Bundled incoming-IM sound, per-message DM sound defaults, Click 2 on already-focused floater clicks, and single-sound floater closing without extra button/focus cues. (in progress)

- Prism Animation Overrider (AO), including animation sets, inventory-backed configuration, per-account persistence, a toolbar enable checkbox plus configuration button (in progress), animation synchronization improvements, Firestorm set-folder import/export preserving standard state options, and ZHAO-II/Oracul notecard import with ZHAO-II notecard export. Transfers create new inventory links; unsupported groups/tracks and states are reported. (in progress; transfer interoperability awaiting in-world verification)
- Prism Radar, including full and compact radar floaters, near/far avatar grouping, distance display, search, radar options, toolbar integration, and automatic display behavior.
- Minimalist radar with shadowed text, remembered position, Shift-only dragging, safe click-through without Shift, and protection from Ctrl+W closing. (in progress)
- Radar VIP matching with fuzzy configured-name matching.
- Radar friend highlighting, typing indicators, and muted/blocked-avatar display.
- Radar retains avatars in the current and neighboring regions while dropping distant cached entries after travel. (in progress; runtime verification pending)
- VIP and friend color highlighting in radar and chat.

## Chat and messaging

- DM popouts retain their own size when detached from Conversations, starting at the XUI default of 540×480; reattaching and detaching preserves a manually resized popout. Minimal radar restores its saved bottom-left anchor, independent of list height, and the Now Playing border follows the card's rounded background. (in progress; installer regression testing pending)

- Single-bar Enter-to-chat behavior.
- Compact nearby-chat bar and revised bottom-toolbar layout.
- Nearby chat uses compact `[display name | username]: message` lines with accent-green sender names instead of separate name boxes. (in progress; runtime verification pending)
- Bottom-left custom chat log draws behind normal floating windows. (in progress)
- Inline outgoing translation language selector, shared by the bottom chat bar and Conversations nearby chat. (in progress)
- Offer notifications no longer skip the next participant DM when no duplicate notification log is present. (in progress)
- Per-person persistent DM translation targets and chiclet-reopened hidden DM windows. (in progress)
- Outgoing translation language field in group and conference DMs, with a separate saved target for each conversation and the original outgoing text shown locally in parentheses after its translation. (in progress; runtime verification pending)
- Saved DM translation targets are used only while automatic translation is enabled; explicit `/tr` commands remain available. (in progress; runtime verification pending)
- Automatic translation of nearby chat and IMs.
- Multiple translation providers, including an OpenAI-compatible translation handler.
- OpenAI-compatible translation prompt requests natural, meaning-preserving phrasing and explicitly ignores URL contents while preserving links. (in progress)
- Asynchronous translation that displays the original immediately and updates the message when translation completes.
- Safe handling of simultaneous translation requests that finish out of order.
- Translation markers, failure handling, and suppression of unnecessary same-language translations.
- Exclusion of self-authored messages from incoming automatic translation.
- Group-chat ignore settings.
- Group-invitation ignore setting.
- Improved detached IM behavior, stable centered tear-off placement, and notification bubbles. (in progress)
- Incoming-message window/taskbar flashing without typing-state flashes. (in progress)
- New incoming DM bubbles have a subtle entrance animation. (in progress; runtime verification pending)
- VIP and friend coloring in chat history.
- Modernized incoming/outgoing IM bubbles with character-level selection across messages, readable theme selection colors, viewport-sized rows, independent row/caret positioning for stable resizing, compact mirrored speaker headers, live-previewable configurable colors, and subtle drop shadows. (in progress; selection and resize fixes awaiting runtime verification)

## Avatar and world interaction

- `[sss]` linkset-description skin lighting for tagged surfaces and test prims (attachment-name fallback), editable comma-separated mesh body-part whitelist with case-insensitive substring matching across nearby avatars and affected-surface highlighting, with wrapped lighting, screen diffusion, or a Combined mode adding adjustable wrap and directional transmission with estimated thickness; controls under Graphics > Skin Scattering. Supports opaque and alpha-masked surfaces, excluding the default avatar mesh. Remote detection uses rendered attachment positions, refreshes draw batches when names arrive, uses full attachment-property requests with transient-selection cleanup, and bounds metadata queue work. Enabled by default with the tuned Combined preset; the Skin Scattering tab scrolls to fit whitelist controls. (in progress; default and whitelist changes awaiting in-world verification)
- Nearby-avatar worn-attachments inspector with attachment points, attachment names, and linked creator profiles. (in progress)
- Avatar look-at crosshairs with visible avatar names.
- Correct 3D-depth rendering for look-at crosshairs.
- Typing indicators integrated into avatar/radar presentation.
- Camera movement and zoom-limit changes.
- Avatar animation synchronization improvements; enabled by default. (in progress)
- Tuned first-run preferences: start-location selector, mouselook body, readable profile text, translation after provider setup, gesture muting, group-invite suppression and left-click action blocking enabled; appearance camera movement disabled; 128 m draw distance, SMAA and 0.65 chat bubble opacity, with a softer sage/gray/pink chat palette and green/slate IM bubbles. Existing saved choices and hardware graphics presets still take precedence. (in progress)
- T-Pose toolbar floater with Firestorm pose choices and temporary built-in AO suspension, restoring the prior enabled state when closed. (in progress)
- Attachment visibility and rendering adjustments.
- Animation-stable avatar nameplate positioning with avatar-relative height. (in progress)
- Avatar name tags block clicks from reaching world objects behind them. (in progress; runtime verification pending)

## Profiles and inventory

- Inventory Cleanup with whole demo-folder discovery based only on folder names, with full descendant review, same-asset copy groups, possible object versions, acquired-before review, saved protected folders, and mandatory exact-identity review before bounded moves to Trash, including frozen folder membership and overlap checks. Linked targets, worn items, outfit folders, and Marketplace contents are excluded; stale reviews are rejected. (in progress; Release build and 31 regression checks verified; runtime verification pending)
- Inventory Cleanup landing page with four themed square tool cards, focused results screens, protected-folder toggle, and loading diagnostics shown only on request. (in progress; Release build and existing regression checks passed; UI runtime verification pending)
- Inventory Cleanup loading diagnostics with live folder/item and request counts, explicit idle-but-incomplete state, blocker details, and bounded forced refresh of incomplete entries. (in progress; Release build and 20 regression checks passed; runtime verification pending)
- Inventory cache restores now mark successfully parsed, valid item records complete, avoiding unnecessary per-item refetches and stalled cleanup scans after login. (in progress; Release build verified; runtime verification pending)

- Inventory search operators for multiple required terms, excluded terms, and exact phrases. (in progress)
- Alt-click recursive expansion and collapse for inventory folder trees. (in progress)
- Improved profile texture viewers and modal sizing/behavior, including an unconstrained default, native-size initial previews, centered resizing, independently closable picks previews, and focused-window closing (in progress).
- Profile, classified, and picks loading improvements.
- Removal of individual items from outfits.
- Dragging individual or multiple inventory items into outfits.
- Customized inventory folder icons.

## Asset loading and reliability

- Exact-OIT alpha rendering for correctly composited overlapping transparent surfaces, with bounded GPU memory and automatic vanilla-renderer fallback.
- OIT surface lighting normalizes interpolated normals, removes the extra Classic-mode local-light boost, and matches the opaque PBR point-light intensity multiplier through its shared transparency shaders. (in progress; Release build, 36 GPU lighting cases, and 14 alpha shader syntax checks passed; in-world lighting verification pending)
- Exact OIT uses GPU-selected sort passes and same-frame overflow fallback, delayed nonblocking statistics, GPU counter resets, and tiled maximum-depth reduction; synchronous validation and per-fragment maximum updates remain selectable for comparison. (in progress; direct GPU correctness checks pass; in-world visual and performance verification pending)
- Particle rendering skips glow passes for batches with no glow, and Exact OIT skips zero-glow capture entries while preserving glowing ribbon endpoints. (in progress; awaiting in-world performance and visual verification)
- Legacy alpha-blended surfaces reject transparent texels before filtered shadow sampling in both ordinary and Exact OIT rendering, retaining the existing alpha cutoff and shadow quality. (in progress; awaiting dense-foliage performance and visual verification)
- Shadow casting skips unused forward-alpha list construction and skin-scattering uniform setup, and reuses alpha-caster shader setup across consecutive batches. (in progress; awaiting in-world CPU timing and shadow verification)
- Plain opaque shadow draws combine consecutive index ranges sharing a vertex buffer and transform; disabled cascades skip receiver-bound traversal and shadow fitting preallocates its temporary point arrays. (in progress; awaiting in-world performance and shadow verification)
- Masked shadow draws merge compatible adjacent ranges and reuse unchanged alpha cutoffs; receiver-bound searches stop below fully enclosed nonempty groups, and shaders skip unused modelview inversions. (in progress; automated regression checks pass; in-world performance and visual verification pending)
- Texture-priority work reuses loop inputs and complete cached face-projection results; avatar appearance writes reuse fixed texture-slot assignments, skip already-assigned texture fetches, and avoid duplicate parameter lookups while retaining driver and animation updates. (in progress; automated checks pass; appearance, texture-quality, and performance verification pending)

- Texture retry and failed-asset handling improvements.
- Mesh retry and loading changes.
- Asset-loading documentation.
- Viewer crash, shutdown, and related reliability fixes.

## Interface and preferences

- Session Money Log floater for successful incoming and outgoing L$ transactions, with counterparties, transaction context, timestamps, live "seconds ago" ages, and clearing. (in progress)
- Dedicated Prism preferences panel.
- Preference to prevent left-click world-object actions while retaining action cursors. (in progress; runtime verification pending)
- Notification list timestamps display live relative ages. (in progress; runtime verification pending)
- Toolbar commands for AO, radar, and translation.
- Crystal-to-wireframe Prism application and taskbar icons, Windows installer icons, and Mac/Linux icon sets, with flat white vertices and edges for contrast and transparent multi-resolution assets. (in progress; installer and other-platform verification pending)
- Custom fonts and font configuration.
- Customized modal, floater, toast, scrollbar, button, tab, themed single- and multiline text fields, unified green accent states, and chat styling (multiline refresh in progress; tab and accent refresh in progress).
- Subtle hover gradient on floater backgrounds (in progress).
- Separated top-center DM chiclets and top-right notification controls; notification popup anchors beneath the relocated top-right control (in progress; runtime verification pending).
- Custom colors for VIP, friend, blocked, and radar states.
- Volume and audio UI adjustments.
- Themed Now Playing card with a top-right visibility toggle, copyable stream URL and track title, pause-aware listening time, decorative playback bars, and parcel-music volume control, positioned clear of the right-side notifications. (in progress)
- Parcel music plugin initialization and retry fixes, playback error notifications and connection status, and optional "Now playing" song announcements in nearby chat (Preferences > Sound > Song in chat; enabled by default). (in progress)
- Group visibility and notification preferences.

## Maintenance notes

- This is a general feature inventory, not a complete changelog.
- When a major user-facing feature is added or substantially changed, update the relevant section and add a concise bullet here.
- Keep unfinished work clearly identified until it is committed or otherwise confirmed complete.
