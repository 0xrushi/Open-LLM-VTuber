#!/usr/bin/env python3
import time
import math
import json
import requests

API_URL = "http://localhost:12393/vrm/motion"

# Bones we care about
BONES = [
    "rightUpperArm",
    "leftUpperArm",
    "rightLowerArm",
    "leftLowerArm",
    "spine",
    "head",
]

def send_pose(pose):
    """
    pose: dict { bone_name: (x, y, z) }
    Sends a single frame to the VRM server.
    """
    bones_payload = []
    for name in BONES:
        x, y, z = pose.get(name, (0.0, 0.0, 0.0))
        bones_payload.append({
            "name": name,
            "rotation": {"x": x, "y": y, "z": z}
        })

    requests.post(
        API_URL,
        headers={"Content-Type": "application/json"},
        data=json.dumps({"bones": bones_payload}),
        timeout=0.3
    )

# --------- BASE POSES (clamped / natural) ---------

def pose_neutral():
    return {b: (0.0, 0.0, 0.0) for b in BONES}

def pose_soft_neutral():
    p = pose_neutral()
    p["rightUpperArm"] = (0.0, 0.0, -0.3)
    p["leftUpperArm"]  = (0.0, 0.0,  0.3)
    p["rightLowerArm"] = (0.0, 0.0, -0.3)
    p["leftLowerArm"]  = (0.0, 0.0,  0.3)
    return p

def pose_arms_up():
    p = pose_soft_neutral()
    p["rightUpperArm"] = (0.0, 0.0, -1.4)
    p["leftUpperArm"]  = (0.0, 0.0,  1.4)
    p["rightLowerArm"] = (0.0, 0.0, -0.6)
    p["leftLowerArm"]  = (0.0, 0.0,  0.6)
    return p

def pose_arms_bent():
    p = pose_soft_neutral()
    p["rightUpperArm"] = (0.0, 0.0, -0.7)
    p["leftUpperArm"]  = (0.0, 0.0,  0.7)
    p["rightLowerArm"] = (0.0, 0.0, -1.0)
    p["leftLowerArm"]  = (0.0, 0.0,  1.0)
    return p

def pose_lean_right():
    p = pose_soft_neutral()
    p["spine"]         = (0.0, 0.0, -0.3)
    p["head"]          = (0.0, 0.0,  0.3)
    p["rightUpperArm"] = (0.0, 0.0, -1.0)
    p["leftUpperArm"]  = (0.0, 0.0,  0.6)
    p["rightLowerArm"] = (0.0, 0.0, -0.8)
    p["leftLowerArm"]  = (0.0, 0.0,  0.8)
    return p

def pose_lean_left():
    p = pose_soft_neutral()
    p["spine"]         = (0.0, 0.0,  0.3)
    p["head"]          = (0.0, 0.0, -0.3)
    p["rightUpperArm"] = (0.0, 0.0, -0.6)
    p["leftUpperArm"]  = (0.0, 0.0,  1.0)
    p["rightLowerArm"] = (0.0, 0.0, -0.8)
    p["leftLowerArm"]  = (0.0, 0.0,  0.8)
    return p

def pose_wave_right_up():
    p = pose_soft_neutral()
    p["rightUpperArm"] = (0.2, 0.0, -1.3)
    p["rightLowerArm"] = (0.2, 0.0, -0.4)
    p["leftUpperArm"]  = (0.0, 0.0,  0.5)
    p["leftLowerArm"]  = (0.0, 0.0,  0.6)
    return p

def pose_wave_right_down():
    p = pose_soft_neutral()
    p["rightUpperArm"] = (0.2, 0.0, -1.3)
    p["rightLowerArm"] = (-0.1, 0.0, -0.8)
    p["leftUpperArm"]  = (0.0, 0.0,  0.5)
    p["leftLowerArm"]  = (0.0, 0.0,  0.6)
    return p

def pose_disco_right():
    p = pose_soft_neutral()
    p["rightUpperArm"] = (0.4,  0.1, -1.4)
    p["rightLowerArm"] = (0.1,  0.0, -0.4)
    p["leftUpperArm"]  = (-0.1, 0.0,  0.8)
    p["leftLowerArm"]  = (0.0,  0.0,  0.8)
    p["spine"]         = (0.0,  0.2,  0.0)
    p["head"]          = (0.0,  0.1,  0.1)
    return p

def pose_disco_left():
    p = pose_soft_neutral()
    p["leftUpperArm"]  = (-0.4, -0.1,  1.4)
    p["leftLowerArm"]  = (-0.1,  0.0,  0.4)
    p["rightUpperArm"] = (0.1,   0.0, -0.8)
    p["rightLowerArm"] = (0.0,   0.0, -0.8)
    p["spine"]         = (0.0,  -0.2,  0.0)
    p["head"]          = (0.0,  -0.1, -0.1)
    return p

# --------- INTERPOLATION ---------

def interpolate_and_send(from_pose, to_pose, max_step=0.3, frame_delay=0.05):
    """
    Interpolates from from_pose to to_pose so that
    no single joint component changes by more than max_step radians
    in a single frame.
    """
    # Ensure pose dicts have all bones
    fp = {b: from_pose.get(b, (0.0, 0.0, 0.0)) for b in BONES}
    tp = {b: to_pose.get(b, (0.0, 0.0, 0.0)) for b in BONES}

    # Find maximum delta over all bones and axes
    max_delta = 0.0
    for b in BONES:
        fx, fy, fz = fp[b]
        tx, ty, tz = tp[b]
        max_delta = max(
            max_delta,
            abs(tx - fx),
            abs(ty - fy),
            abs(tz - fz)
        )

    if max_delta == 0:
        return

    steps = int(math.ceil(max_delta / max_step))
    if steps < 1:
        steps = 1

    for i in range(1, steps + 1):
        t = i / steps
        pose_frame = {}
        for b in BONES:
            fx, fy, fz = fp[b]
            tx, ty, tz = tp[b]
            pose_frame[b] = (
                fx + (tx - fx) * t,
                fy + (ty - fy) * t,
                fz + (tz - fz) * t,
            )
        send_pose(pose_frame)
        time.sleep(frame_delay)

# --------- DANCE SEQUENCE ---------

def main():
    print("🕺 Starting VRM Python Dance! Ctrl+C to stop.")

    current_pose = pose_neutral()
    send_pose(current_pose)
    time.sleep(0.3)

    try:
        while True:
            # Arms up
            next_pose = pose_arms_up()
            interpolate_and_send(current_pose, next_pose, max_step=0.3, frame_delay=0.05)
            current_pose = next_pose
            time.sleep(0.1)

            # Arms bent
            next_pose = pose_arms_bent()
            interpolate_and_send(current_pose, next_pose, max_step=0.3, frame_delay=0.05)
            current_pose = next_pose
            time.sleep(0.1)

            # Lean right
            next_pose = pose_lean_right()
            interpolate_and_send(current_pose, next_pose, max_step=0.3, frame_delay=0.05)
            current_pose = next_pose
            time.sleep(0.1)

            # Lean left
            next_pose = pose_lean_left()
            interpolate_and_send(current_pose, next_pose, max_step=0.3, frame_delay=0.05)
            current_pose = next_pose
            time.sleep(0.1)

            # Wave (right arm up/down a few times)
            for _ in range(2):
                next_pose = pose_wave_right_up()
                interpolate_and_send(current_pose, next_pose, max_step=0.3, frame_delay=0.04)
                current_pose = next_pose
                time.sleep(0.05)

                next_pose = pose_wave_right_down()
                interpolate_and_send(current_pose, next_pose, max_step=0.3, frame_delay=0.04)
                current_pose = next_pose
                time.sleep(0.05)

            # Back to soft neutral briefly
            next_pose = pose_soft_neutral()
            interpolate_and_send(current_pose, next_pose, max_step=0.3, frame_delay=0.05)
            current_pose = next_pose
            time.sleep(0.1)

            # Disco right / left
            for _ in range(2):
                next_pose = pose_disco_right()
                interpolate_and_send(current_pose, next_pose, max_step=0.3, frame_delay=0.05)
                current_pose = next_pose
                time.sleep(0.1)

                next_pose = pose_disco_left()
                interpolate_and_send(current_pose, next_pose, max_step=0.3, frame_delay=0.05)
                current_pose = next_pose
                time.sleep(0.1)

            # Return to neutral at end of loop for smooth restart
            next_pose = pose_neutral()
            interpolate_and_send(current_pose, next_pose, max_step=0.3, frame_delay=0.05)
            current_pose = next_pose
            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\n🛑 Stopping, returning to neutral...")
    finally:
        neutral = pose_neutral()
        interpolate_and_send(current_pose, neutral, max_step=0.3, frame_delay=0.05)
        send_pose(neutral)

if __name__ == "__main__":
    main()
