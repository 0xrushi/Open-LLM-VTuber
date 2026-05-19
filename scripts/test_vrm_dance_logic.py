import math

def mock_retarget_hips_v1(y_mixamo, scale=0.01):
    """Previous logic: result = y_mixamo * scale"""
    return y_mixamo * scale

def mock_retarget_hips_v2(y_mixamo, rest_y, first_frame_y):
    """New logic: result = rest_y + (y_mixamo - first_frame_y) * (rest_y / first_frame_y)"""
    scale = rest_y / first_frame_y
    return rest_y + (y_mixamo - first_frame_y) * scale

def test_hips_position():
    print("Testing Hips Position Scaling Logic...")
    
    # Typical Mixamo values: rest height ~100 units
    # Typical VRM values: rest height ~0.9 units
    rest_y_vrm = 0.9
    first_frame_y_mixamo = 100.0
    
    # Case 1: Rest pose (first frame)
    v1_rest = mock_retarget_hips_v1(first_frame_y_mixamo, scale=0.9/100.0)
    v2_rest = mock_retarget_hips_v2(first_frame_y_mixamo, rest_y_vrm, first_frame_y_mixamo)
    
    print(f"Rest Pose - V1: {v1_rest:.4f}, V2: {v2_rest:.4f} (Expected: {rest_y_vrm})")
    assert math.isclose(v2_rest, rest_y_vrm), "V2 should place hips exactly at rest height on first frame"

    # Case 2: Animation bobs up by 10 units (10%)
    bob_up = 110.0
    v1_up = mock_retarget_hips_v1(bob_up, scale=0.9/100.0)
    v2_up = mock_retarget_hips_v2(bob_up, rest_y_vrm, first_frame_y_mixamo)
    
    print(f"Bob Up    - V1: {v1_up:.4f}, V2: {v2_up:.4f} (Expected: {rest_y_vrm * 1.1:.4f})")
    assert math.isclose(v2_up, rest_y_vrm * 1.1), "V2 should maintain relative bobbing scale"

    print("✅ Hips Position Logic Test Passed!\n")

def test_z_roll_stripping_logic():
    print("Testing Z-Roll Stripping Logic...")
    
    bones = ["Spine", "Chest", "UpperChest", "LeftUpperLeg", "RightUpperLeg"]
    
    def should_strip_z(bone_name, disable_flag):
        is_trunk = bone_name in ["Spine", "Chest", "UpperChest"]
        return is_trunk and not disable_flag

    # Old behavior: Legs were stripped
    print("Old Behavior (conceptually): Legs were stripped of Z-roll")
    
    # New behavior: Legs are NOT stripped, even if flag is false
    assert not should_strip_z("LeftUpperLeg", False), "Legs should never be stripped now"
    assert not should_strip_z("RightUpperLeg", False), "Legs should never be stripped now"
    
    # Flag behavior: Nothing is stripped if disable_flag is true
    assert not should_strip_z("Spine", True), "Spine should not be stripped if flag is True"
    
    # Default behavior: Trunk bones are still stripped for stability in idle
    assert should_strip_z("Spine", False), "Spine should still be stripped by default for stability"

    print("✅ Z-Roll Stripping Logic Test Passed!")

if __name__ == "__main__":
    test_hips_position()
    test_z_roll_stripping_logic()
