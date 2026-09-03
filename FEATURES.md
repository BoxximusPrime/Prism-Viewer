# BoxxyViewer Feature Inventory

This document tracks major features and user-facing customizations added to BoxxyViewer beyond the official Second Life viewer.

The committed feature list is based on the differences from the `upstream/develop` branch, the BoxxyViewer commit history, and related development notes. Current uncommitted changes may include additional work in progress and should not be treated as final until committed.

## BoxxyViewer-specific systems

- Boxxy Animation Overrider (AO), including animation sets, inventory-backed configuration, per-account persistence, toolbar/floater controls, and animation synchronization improvements.
- Boxxy Radar, including full and compact radar floaters, near/far avatar grouping, distance display, search, radar options, toolbar integration, and automatic display behavior.
- Radar VIP matching with fuzzy configured-name matching.
- Radar friend highlighting, typing indicators, and muted/blocked-avatar display.
- VIP and friend color highlighting in radar and chat.

## Chat and messaging

- Single-bar Enter-to-chat behavior.
- Compact nearby-chat bar and revised bottom-toolbar layout.
- Inline outgoing translation language selector.
- Automatic translation of nearby chat and IMs.
- Multiple translation providers, including an OpenAI-compatible translation handler.
- Asynchronous translation that displays the original immediately and updates the message when translation completes.
- Safe handling of simultaneous translation requests that finish out of order.
- Translation markers, failure handling, and suppression of unnecessary same-language translations.
- Exclusion of self-authored messages from incoming automatic translation.
- Group-chat ignore settings.
- Group-invitation ignore setting.
- Improved detached IM behavior and notification bubbles.
- Incoming-message window/taskbar flashing.
- VIP and friend coloring in chat history.

## Avatar and world interaction

- Avatar look-at crosshairs with visible avatar names.
- Correct 3D-depth rendering for look-at crosshairs.
- Typing indicators integrated into avatar/radar presentation.
- Camera movement and zoom-limit changes.
- Avatar animation synchronization improvements.
- Attachment visibility and rendering adjustments.

## Profiles and inventory

- Improved profile texture viewers and modal sizing/behavior.
- Profile, classified, and picks loading improvements.
- Removal of individual items from outfits.
- Dragging individual or multiple inventory items into outfits.
- Customized inventory folder icons.

## Asset loading and reliability

- Texture retry and failed-asset handling improvements.
- Mesh retry and loading changes.
- Asset-loading documentation.
- Viewer crash, shutdown, and related reliability fixes.

## Interface and preferences

- Dedicated BoxxyViewer preferences panel.
- Toolbar commands for AO, radar, and translation.
- Login-screen redesign and customization.
- Custom fonts and font configuration.
- Customized modal, floater, toast, scrollbar, button, text-field, and chat styling.
- Custom colors for VIP, friend, blocked, and radar states.
- Volume and audio UI adjustments.
- Group visibility and notification preferences.

## Maintenance notes

- This is a general feature inventory, not a complete changelog.
- When a major user-facing feature is added or substantially changed, update the relevant section and add a concise bullet here.
- Keep unfinished work clearly identified until it is committed or otherwise confirmed complete.
