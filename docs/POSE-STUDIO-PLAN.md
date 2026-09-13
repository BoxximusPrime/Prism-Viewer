# Pose Studio

## Current scope

Pose Studio provides local self-avatar posing from Avatar > Pose Studio:

- Hold the current pose, edit joint rotation offsets, and reset a bone or pose.
- Browse grouped joints with hierarchy indentation and name search.
- End posing or close the floater to restore normal animation evaluation.
- Preserve the user's AO and animation-freeze preferences.
- End safely when the avatar, skeleton, region or connection changes.

## Animation export removed for 0.4.0

Animation serialization, detached export snapshots, inventory upload, the upload
button and its confirmation/error notifications have been removed at the user's
request. Captured poses must not be converted into reusable animation assets by
Pose Studio. There is no local animation export or inventory upload path.

Skeleton overlays and editable local pose files remain deferred. Animation
export and upload are no longer planned features.

## Validation

The session regression harness exercises production pose and quaternion routines
with a small test skeleton: nonidentity parent/base rotations, descendant
movement, 100 alternating animated/frozen frames, resets, exact restoration and
stale skeleton/target handling. It also checks update ordering and UI wiring.
It does not substitute for in-world testing.

Earlier in-world checks confirmed capture, rotation offsets, resets, AO activity,
End posing, animation-freeze interaction and reset-skeleton recovery. Live
teleport, forced disconnect, shape editing and attachment replacement remain
untested. The 0.4.0 removal passed a fresh Release build, session regression and
login-screen UI check.
