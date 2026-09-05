# BoxxyViewer Feature Inventory

This document tracks major features and user-facing customizations added to BoxxyViewer beyond the official Second Life viewer.

The committed feature list is based on the differences from the `upstream/develop` branch, the BoxxyViewer commit history, and related development notes. Current uncommitted changes may include additional work in progress and should not be treated as final until committed.

## BoxxyViewer-specific systems

- Boxxy Animation Overrider (AO), including animation sets, inventory-backed configuration, per-account persistence, a toolbar enable checkbox plus configuration button (in progress), and animation synchronization improvements.
- Boxxy Radar, including full and compact radar floaters, near/far avatar grouping, distance display, search, radar options, toolbar integration, and automatic display behavior.
- Radar VIP matching with fuzzy configured-name matching.
- Radar friend highlighting, typing indicators, and muted/blocked-avatar display.
- VIP and friend color highlighting in radar and chat.

## Chat and messaging

- Single-bar Enter-to-chat behavior.
- Compact nearby-chat bar and revised bottom-toolbar layout.
- Inline outgoing translation language selector.
- Per-person persistent DM translation targets and chiclet-reopened hidden DM windows. (in progress)
- Automatic translation of nearby chat and IMs.
- Multiple translation providers, including an OpenAI-compatible translation handler.
- Asynchronous translation that displays the original immediately and updates the message when translation completes.
- Safe handling of simultaneous translation requests that finish out of order.
- Translation markers, failure handling, and suppression of unnecessary same-language translations.
- Exclusion of self-authored messages from incoming automatic translation.
- Group-chat ignore settings.
- Group-invitation ignore setting.
- Improved detached IM behavior, stable centered tear-off placement, and notification bubbles. (in progress)
- Incoming-message window/taskbar flashing without typing-state flashes. (in progress)
- VIP and friend coloring in chat history.
- Modernized incoming/outgoing IM bubbles with character-level selection across messages, readable theme selection colors, viewport-sized rows, independent row/caret positioning for stable resizing, compact mirrored speaker headers, live-previewable configurable colors, and subtle drop shadows. (in progress; selection and resize fixes awaiting runtime verification)

## Avatar and world interaction

- Nearby-avatar worn-attachments inspector with attachment points, attachment names, and linked creator profiles. (in progress)
- Avatar look-at crosshairs with visible avatar names.
- Correct 3D-depth rendering for look-at crosshairs.
- Typing indicators integrated into avatar/radar presentation.
- Camera movement and zoom-limit changes.
- Avatar animation synchronization improvements.
- Attachment visibility and rendering adjustments.
- Animation-stable avatar nameplate positioning with avatar-relative height. (in progress)

## Profiles and inventory

- Inventory search operators for multiple required terms, excluded terms, and exact phrases. (in progress)
- Alt-click recursive expansion and collapse for inventory folder trees. (in progress)
- Improved profile texture viewers and modal sizing/behavior, including an unconstrained default, native-size initial previews, centered resizing, independently closable picks previews, and focused-window closing (in progress).
- Profile, classified, and picks loading improvements.
- Removal of individual items from outfits.
- Dragging individual or multiple inventory items into outfits.
- Customized inventory folder icons.

## Asset loading and reliability

- Exact-OIT alpha rendering for correctly composited overlapping transparent surfaces, with bounded GPU memory and automatic vanilla-renderer fallback.

- Texture retry and failed-asset handling improvements.
- Mesh retry and loading changes.
- Asset-loading documentation.
- Viewer crash, shutdown, and related reliability fixes.

## Interface and preferences

- Session Money Log floater for successful incoming and outgoing L$ transactions, with counterparties, transaction context, timestamps, live "seconds ago" ages, and clearing. (in progress)
- Dedicated BoxxyViewer preferences panel.
- Toolbar commands for AO, radar, and translation.
- Login-screen redesign and Boxxy cube branding across application, taskbar, installer, startup, and login surfaces; larger login cube, consistently sized location dropdown, and accent-green login button. (in progress)
- Custom fonts and font configuration.
- Customized modal, floater, toast, scrollbar, button, tab, themed single- and multiline text fields, unified green accent states, and chat styling (multiline refresh in progress; tab and accent refresh in progress).
- Subtle hover gradient on floater backgrounds (in progress).
- Separated top-center DM chiclets and top-right notification controls (in progress).
- Custom colors for VIP, friend, blocked, and radar states.
- Volume and audio UI adjustments.
- Group visibility and notification preferences.

## Maintenance notes

- This is a general feature inventory, not a complete changelog.
- When a major user-facing feature is added or substantially changed, update the relevant section and add a concise bullet here.
- Keep unfinished work clearly identified until it is committed or otherwise confirmed complete.
