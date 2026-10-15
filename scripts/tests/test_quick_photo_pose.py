"""Check Quick Photo's authored joint rotations against the viewer's real skeleton."""
from pathlib import Path
import math
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'indra/newview/llfloaterquickphoto.cpp').read_text(encoding='utf-8')
motion = source.split('class LLQuickPhotoMotion final', 1)[1].split('\n};', 1)[0]
angles = {name: math.radians(float(roll))
          for name, roll in re.findall(r'\{"(m\w+)", (-?[\d.]+)f\}', motion)}
assert len(angles) == 25

def multiply(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3))
                       for j in range(3)) for i in range(3))

def rotate(r, v):
    return tuple(sum(r[i][j] * v[j] for j in range(3)) for i in range(3))

identity = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
joints = {}

def visit(node, position=(0, 0, 0), rotation=identity):
    for bone in node.findall('bone'):
        name = bone.get('name')
        offset = rotate(rotation, tuple(map(float, bone.get('pos').split())))
        current = tuple(position[i] + offset[i] for i in range(3))
        a = angles.get(name, 0)
        local = ((1, 0, 0), (0, math.cos(a), -math.sin(a)), (0, math.sin(a), math.cos(a)))
        world = multiply(rotation, local)
        joints[name] = (current, world)
        visit(bone, current, world)

visit(ET.parse(ROOT / 'indra/newview/character/avatar_skeleton.xml').getroot())
assert set(angles) <= joints.keys()
for name in ('mEyeLeft', 'mEyeRight', 'mFaceEyeAltLeft', 'mFaceEyeAltRight'):
    assert name in angles and angles[name] == 0
    assert rotate(joints[name][1], (1, 0, 0)) == (1, 0, 0)  # Both eye rigs face forward.
for side in ('Left', 'Right'):
    shoulder, wrist = (joints['m' + bone + side][0] for bone in ('Shoulder', 'Wrist'))
    arm = tuple(wrist[i] - shoulder[i] for i in range(3))
    assert arm[2] < -0.4  # Arms point down, not horizontally or upward.
    angle = math.degrees(math.atan2(abs(arm[1]), -arm[2]))
    assert abs(angle - 20) < 0.1, angle
    assert all(abs(joints['mFoot' + side][1][i][j] - identity[i][j]) < 1e-6
               for i in range(3) for j in range(3))  # Level feet after outward hip rotation.
    hip, ankle = (joints['m' + bone + side][0] for bone in ('Hip', 'Ankle'))
    leg_angle = math.degrees(math.atan2(abs(ankle[1] - hip[1]), hip[2] - ankle[2]))
    assert leg_angle < 0.5, leg_angle  # Feet directly under the hips in the frontal view.
left, right = (joints['mAnkle' + side][0] for side in ('Left', 'Right'))
assert 0.24 < left[1] - right[1] < 0.28  # Natural hip-width stance on the reference skeleton.
assert abs(left[2] - right[2]) < 0.002
assert 'state->setUsage(LLJointState::ROT)' in motion  # Preserve body proportions/mesh offsets.
assert 'return NORMAL_BLEND' in motion and 'return LLJoint::ADDITIVE_PRIORITY' in motion
assert 'registerMotion(PHOTO_POSE, LLQuickPhotoMotion::create)' in source
assert 'LLCharacter::stopMotion(PHOTO_POSE, true)' in source
assert 'sendAnimationRequest' not in source
print('Low A pose: arms 20 degrees from vertical, legs vertical, level feet, both eye rigs facing forward; local motion wiring passed.')
