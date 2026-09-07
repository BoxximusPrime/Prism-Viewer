# Bundled UI sounds

Copied unchanged from the user-provided `RCTSounds` folder and Downloads. UUID filenames let
the standard viewer audio engine load these locally, using UI volume/mute settings.

| Original file | Bundled UUID | UI event |
| --- | --- | --- |
| Click 1.wav | 43c4ee7d-22c5-479d-8ac9-b7415e70c09d | Button press/release, respecting each button's sound flags |
| Click 2.wav | 0d043efb-d04d-4455-9728-bd26c7211180 | Floater clicks (including already focused windows) and keyboard focus changes |
| Click 3.wav | e16876ed-bd4b-4262-85e8-3ce3f5995c21 | Checkbox commit |
| Window Open.wav | d2a01341-0605-43ce-9bb1-6019585d36c3 | Floater opened |
| se_pb34taaxru23rieu.wav (Downloads) | 166afcab-e75a-44b5-a251-c56f57a9fc90 | Incoming IM notifications |

Closing a floater uses Click 1 once, suppressing its X-button click and focus-handoff sound.

RCT source format: 16-bit mono PCM WAV, 22050 Hz. The incoming-IM WAV is
16-bit stereo PCM, 44100 Hz. Distribution rights are not
established by this copy; verify permission before distributing these assets.
